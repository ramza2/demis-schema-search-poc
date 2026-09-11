"""Gold dataset loading and validation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import CatalogColumn, CatalogTable

VALID_CATEGORIES = frozenset(
    {
        "clinical_natural_language",
        "paraphrase",
        "schema_semantic",
        "physical_identifier",
        "ambiguous",
        "relation",
    }
)

_TABLE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_COLUMN_ID_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$"
)


@dataclass
class GoldTargets:
    primary_tables: list[str] = field(default_factory=list)
    acceptable_tables: list[str] = field(default_factory=list)
    relevant_columns: list[str] = field(default_factory=list)
    relation_tables: list[str] = field(default_factory=list)
    gold_relation_paths: list[list[str]] = field(default_factory=list)

    @property
    def relevant_tables(self) -> list[str]:
        return list(dict.fromkeys([*self.primary_tables, *self.acceptable_tables]))


@dataclass
class GoldQuery:
    id: str
    category: str
    query: str
    gold: GoldTargets


@dataclass
class GoldDataset:
    version: str
    queries: list[GoldQuery]
    path: Path | None = None
    content_hash: str = ""


class GoldValidationError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_gold_dataset(path: Path | str) -> GoldDataset:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    version = str(raw.get("version") or "1")
    queries: list[GoldQuery] = []
    for item in raw.get("queries") or []:
        g = item.get("gold") or {}
        queries.append(
            GoldQuery(
                id=str(item["id"]),
                category=str(item.get("category") or "").strip(),
                query=str(item.get("query") or "").strip(),
                gold=GoldTargets(
                    primary_tables=list(g.get("primary_tables") or []),
                    acceptable_tables=list(g.get("acceptable_tables") or []),
                    relevant_columns=list(g.get("relevant_columns") or []),
                    relation_tables=list(g.get("relation_tables") or []),
                    gold_relation_paths=list(g.get("gold_relation_paths") or []),
                ),
            )
        )
    return GoldDataset(
        version=version,
        queries=queries,
        path=path,
        content_hash=file_sha256(path),
    )


def _catalog_identities(session: Session) -> tuple[set[str], set[str]]:
    tables = list(session.scalars(select(CatalogTable).where(CatalogTable.active.is_(True))).all())
    table_ids = {f"{t.schema_name}.{t.table_name}" for t in tables}
    by_id = {t.id: t for t in tables}
    cols = list(session.scalars(select(CatalogColumn)).all())
    col_ids: set[str] = set()
    for c in cols:
        t = by_id.get(c.table_id)
        if t is None:
            continue
        col_ids.add(f"{t.schema_name}.{t.table_name}.{c.column_name}")
    return table_ids, col_ids


def validate_gold_dataset(
    dataset: GoldDataset,
    *,
    session: Session | None = None,
    require_catalog: bool = True,
) -> list[str]:
    """Return list of validation error messages (empty if valid)."""
    errors: list[str] = []
    if not dataset.queries:
        errors.append("gold dataset has no queries")
    ids = [q.id for q in dataset.queries]
    if len(ids) != len(set(ids)):
        seen: set[str] = set()
        for qid in ids:
            if qid in seen:
                errors.append(f"duplicate query id: {qid}")
            seen.add(qid)

    table_ids: set[str] | None = None
    col_ids: set[str] | None = None
    if require_catalog:
        if session is None:
            errors.append("catalog session required for gold validation")
        else:
            table_ids, col_ids = _catalog_identities(session)

    for q in dataset.queries:
        if not q.id.strip():
            errors.append("empty query id")
        if not q.query.strip():
            errors.append(f"{q.id}: empty query text")
        if q.category not in VALID_CATEGORIES:
            errors.append(f"{q.id}: invalid category {q.category!r}")
        g = q.gold
        if not (g.primary_tables or g.acceptable_tables or g.relevant_columns or g.relation_tables):
            errors.append(f"{q.id}: gold has no targets")

        for tid in [*g.primary_tables, *g.acceptable_tables, *g.relation_tables]:
            if not _TABLE_ID_RE.fullmatch(tid):
                errors.append(f"{q.id}: invalid table identity {tid!r}")
            elif table_ids is not None and tid not in table_ids:
                errors.append(f"{q.id}: unknown gold table {tid}")
        for cid in g.relevant_columns:
            if not _COLUMN_ID_RE.fullmatch(cid):
                errors.append(f"{q.id}: invalid column identity {cid!r}")
            elif col_ids is not None and cid not in col_ids:
                errors.append(f"{q.id}: unknown gold column {cid}")
        for path in g.gold_relation_paths:
            for tid in path:
                if not _TABLE_ID_RE.fullmatch(tid):
                    errors.append(f"{q.id}: invalid relation path table {tid!r}")
                elif table_ids is not None and tid not in table_ids:
                    errors.append(f"{q.id}: unknown relation path table {tid}")
    return errors


def assert_valid_gold(dataset: GoldDataset, *, session: Session | None = None) -> None:
    errors = validate_gold_dataset(dataset, session=session, require_catalog=session is not None)
    if errors:
        raise GoldValidationError("; ".join(errors[:20]) + (" ..." if len(errors) > 20 else ""))
