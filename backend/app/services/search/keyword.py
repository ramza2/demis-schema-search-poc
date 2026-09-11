"""Keyword search over search documents (PostgreSQL only, no ES)."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[가-힣]+")


@dataclass
class KeywordHit:
    document_id: int
    document_key: str
    object_type: str
    table_name: str | None
    column_name: str | None
    searchable_text: str
    keyword_score: float
    keyword_rank: int
    matched_terms: list[str]


def tokenize(text_value: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text_value or "") if t.strip()]


def keyword_search(
    session: Session,
    *,
    original_query: str,
    expanded_query: str,
    original_terms: list[str],
    expanded_terms: list[str],
    limit: int,
    object_type: str | None = None,
) -> tuple[list[KeywordHit], float]:
    """
    OR-based candidate retrieval with explainable weighted scoring.

    Weights (higher is better):
    - exact physical identifier in document_key / table / column: 50
    - original query term substring match in searchable_text: 5
    - expanded alias match: 2
    - simple FTS ts_rank bonus: up to ~1
    """
    terms = list(dict.fromkeys([*original_terms, *expanded_terms]))
    if not terms and not (original_query or "").strip():
        return [], 0.0

    type_filter = ""
    params: dict = {"limit": limit}
    if object_type and object_type.upper() in {"TABLE", "COLUMN"}:
        type_filter = "AND d.object_type = :object_type"
        params["object_type"] = object_type.upper()

    # Build OR ILIKE predicates for candidate retrieval.
    or_clauses: list[str] = []
    for i, term in enumerate(terms[:40]):
        key = f"t{i}"
        params[key] = f"%{term}%"
        or_clauses.append(
            f"(d.document_key ILIKE :{key} OR d.searchable_text ILIKE :{key} "
            f"OR t.table_name ILIKE :{key} OR c.column_name ILIKE :{key})"
        )

    if not or_clauses:
        return [], 0.0

    # Optional FTS query (simple config; Korean treated as raw tokens).
    fts_terms = [re.sub(r"[^A-Za-z0-9가-힣_]+", "", t) for t in terms[:20]]
    fts_terms = [t for t in fts_terms if t]
    fts_query = " | ".join(fts_terms) if fts_terms else ""
    params["fts"] = fts_query

    sql = f"""
        SELECT
            d.id AS document_id,
            d.document_key,
            d.object_type,
            d.searchable_text,
            t.table_name,
            c.column_name,
            CASE WHEN :fts <> '' THEN ts_rank(
                to_tsvector('simple', coalesce(d.searchable_text, '')),
                to_tsquery('simple', :fts)
            ) ELSE 0 END AS fts_rank
        FROM catalog_search_document d
        LEFT JOIN catalog_table t ON t.id = d.table_id
        LEFT JOIN catalog_column c ON c.id = d.column_id
        WHERE d.active = true
          {type_filter}
          AND ({' OR '.join(or_clauses)})
        LIMIT 500
    """

    t0 = time.perf_counter()
    rows = session.execute(text(sql), params).mappings().all()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    original_l = {t.lower() for t in original_terms}
    expanded_l = {t.lower() for t in expanded_terms if t.lower() not in original_l}
    original_query_l = (original_query or "").strip().lower()

    scored: list[tuple[float, list[str], dict]] = []
    for row in rows:
        score = float(row["fts_rank"] or 0.0)
        matched: list[str] = []
        key = (row["document_key"] or "").lower()
        table = (row["table_name"] or "").lower()
        column = (row["column_name"] or "").lower()
        body = (row["searchable_text"] or "").lower()

        for term in original_l:
            if not term:
                continue
            if term == table or term == column or term in key.split(":"):
                score += 50.0
                matched.append(term)
            elif term in key or term in body:
                score += 5.0
                matched.append(term)

        for term in expanded_l:
            if term and (term in body or term in key or term == table or term == column):
                score += 2.0
                matched.append(term)

        # Boost exact full query identifier if user typed a physical name.
        if original_query_l and (
            original_query_l == table
            or original_query_l == column
            or original_query_l in key
        ):
            score += 80.0
            if original_query_l not in matched:
                matched.append(original_query_l)

        if score <= 0:
            continue
        scored.append((score, matched, dict(row)))

    scored.sort(key=lambda x: (-x[0], x[2]["document_id"]))
    hits: list[KeywordHit] = []
    for i, (score, matched, row) in enumerate(scored[:limit], start=1):
        hits.append(
            KeywordHit(
                document_id=int(row["document_id"]),
                document_key=row["document_key"],
                object_type=row["object_type"],
                table_name=row["table_name"],
                column_name=row["column_name"],
                searchable_text=row["searchable_text"] or "",
                keyword_score=score,
                keyword_rank=i,
                matched_terms=matched,
            )
        )
    return hits, elapsed_ms
