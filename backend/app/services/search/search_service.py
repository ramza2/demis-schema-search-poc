"""Orchestrate Semantic / Keyword / Hybrid schema search (Step 4 / 4.1)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.services.search.keyword import keyword_search, tokenize
from app.services.search.query_normalizer import normalize_query
from app.services.search.relation_expander import RelatedTableHit, TableKey, expand_relations
from app.services.search.rrf import rrf_fuse
from app.services.search.semantic import embedding_count, semantic_search
from app.services.search.terminology import expand_query


class SearchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class DirectResult:
    rank: int
    match_type: str
    object_type: str
    schema_name: str | None
    table_name: str | None
    column_name: str | None
    document_key: str
    document_id: int
    semantic_score: float | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    rrf_score: float | None = None
    evidence: list[str] = field(default_factory=list)
    searchable_snippet: str | None = None


@dataclass
class SearchResult:
    original_query: str
    normalized_query: str
    expanded_query: str
    matched_concepts: list[str]
    expanded_terms: list[str]
    mode: str
    model_key: str | None
    object_type: str
    direct_results: list[DirectResult]
    related_tables: list[RelatedTableHit]
    elapsed_ms: float
    timings: dict[str, float] = field(default_factory=dict)
    debug: dict | None = None


def _candidate_limit(top_k: int, settings: Settings) -> int:
    return max(top_k * settings.search_candidate_multiplier, settings.search_candidate_min)


def _snippet(text: str, limit: int = 240) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


class SchemaSearchService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider

    def search(
        self,
        *,
        query: str,
        mode: str = "hybrid",
        top_k: int = 10,
        object_type: str = "ALL",
        expand_terms: bool = True,
        expand_relations_enabled: bool = True,
        max_relation_hops: int = 2,
        debug: bool = False,
    ) -> SearchResult:
        t_total = time.perf_counter()
        mode_l = (mode or "hybrid").strip().lower()
        if mode_l not in {"semantic", "keyword", "hybrid"}:
            raise SearchError("INVALID_MODE", f"unsupported search mode: {mode}")

        top_k = max(1, min(int(top_k), 50))
        max_relation_hops = max(0, min(int(max_relation_hops), 4))
        obj = (object_type or "ALL").upper()
        obj_filter = None if obj == "ALL" else obj
        if obj_filter not in {None, "TABLE", "COLUMN"}:
            raise SearchError("INVALID_OBJECT_TYPE", f"unsupported object_type: {object_type}")

        norm = normalize_query(query)
        expansion = expand_query(
            norm.normalized, settings=self.settings, enabled=expand_terms
        )

        timings: dict[str, float] = {}
        semantic_hits = []
        keyword_hits = []
        model_key: str | None = None
        provider = self.provider
        cand_k = _candidate_limit(top_k, self.settings)

        if mode_l in {"semantic", "hybrid"}:
            provider = provider or get_embedding_provider(self.settings)
            model_key = provider.model_key
            provider_name = (self.settings.embedding_provider or "").strip().lower()
            if provider_name == "fake" and not self.settings.allow_fake_semantic_search:
                raise SearchError(
                    "SEMANTIC_PROVIDER_NOT_AVAILABLE",
                    "Fake embedding provider is for tests only. "
                    "Set ALLOW_FAKE_SEMANTIC_SEARCH=true for tests, "
                    "or use EMBEDDING_PROVIDER=bge_m3.",
                )
            if embedding_count(self.session, model_key) == 0:
                raise SearchError(
                    "EMBEDDING_NOT_FOUND",
                    f"No embeddings found for model_key={model_key}. "
                    "Run POST /api/v1/embeddings/run first.",
                )
            semantic_query = expansion.expanded_query if expand_terms else norm.normalized
            semantic_hits, q_ms, sem_ms = semantic_search(
                self.session,
                provider=provider,
                query_text=semantic_query,
                limit=cand_k,
                object_type=obj_filter,
            )
            timings["query_embedding_ms"] = q_ms
            timings["semantic_search_ms"] = sem_ms

        if mode_l in {"keyword", "hybrid"}:
            original_terms = tokenize(norm.normalized)
            expanded_terms = tokenize(expansion.expanded_query)
            keyword_hits, kw_ms = keyword_search(
                self.session,
                original_query=norm.normalized,
                expanded_query=expansion.expanded_query,
                original_terms=original_terms,
                expanded_terms=expanded_terms,
                limit=cand_k,
                object_type=obj_filter,
            )
            timings["keyword_search_ms"] = kw_ms

        direct: list[DirectResult] = []
        if mode_l == "semantic":
            for hit in semantic_hits[:top_k]:
                direct.append(
                    DirectResult(
                        rank=hit.semantic_rank,
                        match_type="DIRECT",
                        object_type=hit.object_type,
                        schema_name=hit.schema_name,
                        table_name=hit.table_name,
                        column_name=hit.column_name,
                        document_key=hit.document_key,
                        document_id=hit.document_id,
                        semantic_score=hit.semantic_score,
                        semantic_rank=hit.semantic_rank,
                        evidence=["semantic", *expansion.matched_concepts],
                        searchable_snippet=_snippet(hit.searchable_text),
                    )
                )
        elif mode_l == "keyword":
            for hit in keyword_hits[:top_k]:
                direct.append(
                    DirectResult(
                        rank=hit.keyword_rank,
                        match_type="DIRECT",
                        object_type=hit.object_type,
                        schema_name=hit.schema_name,
                        table_name=hit.table_name,
                        column_name=hit.column_name,
                        document_key=hit.document_key,
                        document_id=hit.document_id,
                        keyword_score=hit.keyword_score,
                        keyword_rank=hit.keyword_rank,
                        evidence=[f"keyword:{t}" for t in hit.matched_terms]
                        + expansion.matched_concepts,
                        searchable_snippet=_snippet(hit.searchable_text),
                    )
                )
        else:
            fused = rrf_fuse(
                semantic_hits=[
                    (h.document_id, h.semantic_score, ["semantic"]) for h in semantic_hits
                ],
                keyword_hits=[
                    (h.document_id, h.keyword_score, h.matched_terms) for h in keyword_hits
                ],
                k=self.settings.search_rrf_k,
            )
            meta = {h.document_id: h for h in [*semantic_hits, *keyword_hits]}
            for hit in fused[:top_k]:
                src = meta.get(hit.document_id)
                if src is None:
                    continue
                direct.append(
                    DirectResult(
                        rank=hit.final_rank or 0,
                        match_type="DIRECT",
                        object_type=src.object_type,
                        schema_name=getattr(src, "schema_name", None),
                        table_name=src.table_name,
                        column_name=src.column_name,
                        document_key=src.document_key,
                        document_id=hit.document_id,
                        semantic_score=hit.semantic_score,
                        semantic_rank=hit.semantic_rank,
                        keyword_score=hit.keyword_score,
                        keyword_rank=hit.keyword_rank,
                        rrf_score=hit.rrf_score,
                        evidence=list(hit.evidence) + expansion.matched_concepts,
                        searchable_snippet=_snippet(src.searchable_text),
                    )
                )

        related: list[RelatedTableHit] = []
        if expand_relations_enabled and max_relation_hops > 0:
            t_rel = time.perf_counter()
            seeds: list[TableKey] = []
            seen: set[TableKey] = set()
            for item in direct:
                if not item.table_name:
                    continue
                key = (item.schema_name or "public", item.table_name)
                if key in seen:
                    continue
                seen.add(key)
                seeds.append(key)
            related = expand_relations(
                self.session,
                seed_tables=seeds[:20],
                max_hops=max_relation_hops,
            )
            direct_keys = {
                (d.schema_name or "public", d.table_name)
                for d in direct
                if d.object_type == "TABLE" and d.table_name
            }
            related = [r for r in related if (r.schema_name, r.table_name) not in direct_keys]
            timings["relation_expansion_ms"] = (time.perf_counter() - t_rel) * 1000.0

        elapsed_ms = (time.perf_counter() - t_total) * 1000.0
        timings["total_ms"] = elapsed_ms

        dbg = None
        if debug:
            dbg = {
                "semantic_candidate_count": len(semantic_hits),
                "keyword_candidate_count": len(keyword_hits),
                "candidate_limit": cand_k,
                "rrf_k": self.settings.search_rrf_k,
                "relation_count": len(related),
                "provider": self.settings.embedding_provider,
            }

        return SearchResult(
            original_query=norm.original,
            normalized_query=norm.normalized,
            expanded_query=expansion.expanded_query,
            matched_concepts=expansion.matched_concepts,
            expanded_terms=expansion.expanded_terms,
            mode=mode_l,
            model_key=model_key,
            object_type=obj,
            direct_results=direct,
            related_tables=related,
            elapsed_ms=elapsed_ms,
            timings=timings,
            debug=dbg,
        )
