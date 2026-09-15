"""Candidate extraction and metric helpers (pure functions)."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class RankedIdentity:
    identity: str
    rank: int  # 1-based first appearance


def table_identity(schema_name: str | None, table_name: str | None) -> str | None:
    if not table_name:
        return None
    return f"{schema_name or 'public'}.{table_name}"


def column_identity(
    schema_name: str | None, table_name: str | None, column_name: str | None
) -> str | None:
    if not table_name or not column_name:
        return None
    return f"{schema_name or 'public'}.{table_name}.{column_name}"


def extract_table_candidates(direct_results: Sequence[Any]) -> list[RankedIdentity]:
    """Deduplicate by schema.table using first appearance rank."""
    seen: dict[str, int] = {}
    for i, row in enumerate(direct_results, start=1):
        schema = getattr(row, "schema_name", None)
        if schema is None and isinstance(row, dict):
            schema = row.get("schema_name")
        table = getattr(row, "table_name", None)
        if table is None and isinstance(row, dict):
            table = row.get("table_name")
        ident = table_identity(schema, table)
        if ident and ident not in seen:
            seen[ident] = i
    return [RankedIdentity(identity=k, rank=r) for k, r in seen.items()]


def extract_column_candidates(direct_results: Sequence[Any]) -> list[RankedIdentity]:
    seen: dict[str, int] = {}
    for i, row in enumerate(direct_results, start=1):
        obj = getattr(row, "object_type", None)
        if obj is None and isinstance(row, dict):
            obj = row.get("object_type")
        if str(obj or "").upper() != "COLUMN":
            continue
        schema = getattr(row, "schema_name", None)
        if schema is None and isinstance(row, dict):
            schema = row.get("schema_name")
        table = getattr(row, "table_name", None)
        if table is None and isinstance(row, dict):
            table = row.get("table_name")
        column = getattr(row, "column_name", None)
        if column is None and isinstance(row, dict):
            column = row.get("column_name")
        ident = column_identity(schema, table, column)
        if ident and ident not in seen:
            seen[ident] = i
    return [RankedIdentity(identity=k, rank=r) for k, r in seen.items()]


def extract_relation_tables(
    direct_results: Sequence[Any],
    related_tables: Sequence[Any],
) -> list[str]:
    """Union of direct table candidates + related expansion targets (dedup, ordered)."""
    out: list[str] = []
    for c in extract_table_candidates(direct_results):
        if c.identity not in out:
            out.append(c.identity)
    for rel in related_tables:
        schema = getattr(rel, "schema_name", None)
        if schema is None and isinstance(rel, dict):
            schema = rel.get("schema_name")
        table = getattr(rel, "table_name", None)
        if table is None and isinstance(rel, dict):
            table = rel.get("table_name")
        ident = table_identity(schema, table)
        if ident and ident not in out:
            out.append(ident)
    return out


def identities_at_k(candidates: Sequence[RankedIdentity], k: int) -> list[str]:
    return [c.identity for c in candidates if c.rank <= k][:k] if k > 0 else []


def top_k_identities(candidates: Sequence[RankedIdentity], k: int) -> list[str]:
    return [c.identity for c in candidates[:k]]


def top1_primary_accuracy(candidates: Sequence[RankedIdentity], primary: Sequence[str]) -> bool:
    if not candidates or not primary:
        return False
    return candidates[0].identity in set(primary)


def hit_at_k(candidates: Sequence[RankedIdentity], relevant: Sequence[str], k: int) -> bool:
    if not relevant:
        return False
    top = set(top_k_identities(candidates, k))
    return bool(top & set(relevant))


def set_recall_at_k(candidates: Sequence[RankedIdentity], relevant: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(top_k_identities(candidates, k))
    return len(top & set(relevant)) / float(len(set(relevant)))


def first_relevant_rank(candidates: Sequence[RankedIdentity], relevant: Sequence[str]) -> int | None:
    rel = set(relevant)
    for c in candidates:
        if c.identity in rel:
            return c.rank
    return None


def reciprocal_rank(rank: int | None) -> float:
    if rank is None or rank <= 0:
        return 0.0
    return 1.0 / float(rank)


def relation_recall(found: Sequence[str], gold: Sequence[str]) -> float:
    if not gold:
        return 0.0
    return len(set(found) & set(gold)) / float(len(set(gold)))


def relation_hit(found: Sequence[str], gold: Sequence[str]) -> bool:
    if not gold:
        return False
    return bool(set(found) & set(gold))


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    # Nearest-rank style for P95
    k = max(1, min(len(xs), int(math.ceil((p / 100.0) * len(xs)))))
    return xs[k - 1]


def mean(values: Sequence[float]) -> float:
    return float(statistics.fmean(values)) if values else 0.0


def median(values: Sequence[float]) -> float:
    return float(statistics.median(values)) if values else 0.0
