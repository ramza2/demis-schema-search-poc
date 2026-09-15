"""Semantic search over catalog_embedding with pgvector cosine distance."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.embeddings.base import EmbeddingProvider
from app.models.catalog import CatalogEmbedding


@dataclass
class SemanticHit:
    document_id: int
    document_key: str
    object_type: str
    schema_name: str | None
    table_name: str | None
    column_name: str | None
    searchable_text: str
    semantic_score: float
    semantic_rank: int


def semantic_search(
    session: Session,
    *,
    provider: EmbeddingProvider,
    query_text: str,
    limit: int,
    object_type: str | None = None,
) -> tuple[list[SemanticHit], float, float]:
    """Exact cosine search. Score = 1 - cosine_distance.

    Returns (hits, query_embedding_ms, semantic_search_ms).
    """
    import time

    t0 = time.perf_counter()
    vectors = provider.embed_texts([query_text])
    query_embedding_ms = (time.perf_counter() - t0) * 1000.0
    if not vectors or not vectors[0]:
        return [], query_embedding_ms, 0.0

    qvec = vectors[0]
    model_key = provider.model_key
    vec_literal = "[" + ",".join(f"{float(x):.8f}" for x in qvec) + "]"

    type_filter = ""
    params: dict = {"model_key": model_key, "limit": int(limit), "qvec": vec_literal}
    if object_type and object_type.upper() in {"TABLE", "COLUMN"}:
        type_filter = "AND d.object_type = :object_type"
        params["object_type"] = object_type.upper()

    sql = f"""
        SELECT
            d.id AS document_id,
            d.document_key,
            d.object_type,
            d.searchable_text,
            t.schema_name,
            t.table_name,
            c.column_name,
            (e.embedding <=> CAST(:qvec AS vector)) AS distance
        FROM catalog_embedding e
        JOIN catalog_search_document d ON d.id = e.search_document_id
        LEFT JOIN catalog_table t ON t.id = d.table_id
        LEFT JOIN catalog_column c ON c.id = d.column_id
        WHERE d.active = true
          AND e.model_key = :model_key
          {type_filter}
        ORDER BY e.embedding <=> CAST(:qvec AS vector)
        LIMIT :limit
    """
    t_search = time.perf_counter()
    rows = session.execute(text(sql), params).mappings().all()
    semantic_search_ms = (time.perf_counter() - t_search) * 1000.0
    hits: list[SemanticHit] = []
    for i, row in enumerate(rows, start=1):
        distance = float(row["distance"])
        hits.append(
            SemanticHit(
                document_id=int(row["document_id"]),
                document_key=row["document_key"],
                object_type=row["object_type"],
                schema_name=row["schema_name"],
                table_name=row["table_name"],
                column_name=row["column_name"],
                searchable_text=row["searchable_text"] or "",
                semantic_score=max(0.0, 1.0 - distance),
                semantic_rank=i,
            )
        )
    return hits, query_embedding_ms, semantic_search_ms


def embedding_count(session: Session, model_key: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CatalogEmbedding)
            .where(CatalogEmbedding.model_key == model_key)
        )
        or 0
    )
