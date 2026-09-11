"""Reciprocal Rank Fusion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RankedHit:
    document_id: int
    semantic_rank: int | None = None
    semantic_score: float | None = None
    keyword_rank: int | None = None
    keyword_score: float | None = None
    rrf_score: float = 0.0
    final_rank: int | None = None
    matched_terms: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def rrf_fuse(
    *,
    semantic_hits: list[tuple[int, float, list[str]]],
    keyword_hits: list[tuple[int, float, list[str]]],
    k: int = 60,
) -> list[RankedHit]:
    """
    Fuse ranked lists with Reciprocal Rank Fusion.

    Each hit tuple: (document_id, score, evidence_or_terms)
    Ranks are 1-based.
    """
    by_id: dict[int, RankedHit] = {}

    for idx, (doc_id, score, evidence) in enumerate(semantic_hits, start=1):
        hit = by_id.setdefault(doc_id, RankedHit(document_id=doc_id))
        hit.semantic_rank = idx
        hit.semantic_score = score
        for e in evidence:
            if e not in hit.evidence:
                hit.evidence.append(e)

    for idx, (doc_id, score, terms) in enumerate(keyword_hits, start=1):
        hit = by_id.setdefault(doc_id, RankedHit(document_id=doc_id))
        hit.keyword_rank = idx
        hit.keyword_score = score
        for t in terms:
            if t not in hit.matched_terms:
                hit.matched_terms.append(t)
            if t not in hit.evidence:
                hit.evidence.append(f"keyword:{t}")

    for hit in by_id.values():
        score = 0.0
        if hit.semantic_rank is not None:
            score += 1.0 / (k + hit.semantic_rank)
        if hit.keyword_rank is not None:
            score += 1.0 / (k + hit.keyword_rank)
        hit.rrf_score = score

    fused = sorted(by_id.values(), key=lambda h: (-h.rrf_score, h.document_id))
    for i, hit in enumerate(fused, start=1):
        hit.final_rank = i
    return fused
