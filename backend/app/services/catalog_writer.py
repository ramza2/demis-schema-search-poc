"""Upsert schema snapshot into schema_catalog."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analyzers.base import SchemaSnapshot
from app.models.catalog import (
    CatalogColumn,
    CatalogIndex,
    CatalogIndexColumn,
    CatalogKeyConstraint,
    CatalogKeyConstraintColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogTable,
)
from app.services.fingerprint import fingerprint


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def table_fp(schema: str, name: str, table_type: str, comment: str | None) -> str:
    return fingerprint(
        {
            "schema_name": schema,
            "table_name": name,
            "table_type": table_type,
            "table_comment": comment or "",
        }
    )


def column_fp(
    schema: str,
    table: str,
    ordinal: int,
    name: str,
    data_type: str,
    nullable: bool,
    default: str | None,
    comment: str | None,
) -> str:
    return fingerprint(
        {
            "schema_name": schema,
            "table_name": table,
            "ordinal_position": ordinal,
            "column_name": name,
            "data_type": data_type,
            "is_nullable": nullable,
            "default_value": default or "",
            "column_comment": comment or "",
        }
    )


def key_constraint_fp(
    schema: str,
    table: str,
    constraint_name: str,
    constraint_type: str,
    columns: list[str],
) -> str:
    return fingerprint(
        {
            "schema_name": schema,
            "table_name": table,
            "constraint_name": constraint_name,
            "constraint_type": constraint_type,
            "columns": columns,
        }
    )


def relation_fp(
    *,
    source_schema: str,
    source_table: str,
    constraint_name: str,
    target_schema: str,
    target_table: str,
    mappings: list[tuple[str, str]],
) -> str:
    return fingerprint(
        {
            "source_schema": source_schema,
            "source_table": source_table,
            "constraint_name": constraint_name,
            "target_schema": target_schema,
            "target_table": target_table,
            "columns": [{"source": s, "target": t} for s, t in mappings],
        }
    )


def index_fp(
    schema: str,
    table: str,
    index_name: str,
    is_unique: bool,
    method: str | None,
    columns: list[str],
) -> str:
    return fingerprint(
        {
            "schema_name": schema,
            "table_name": table,
            "index_name": index_name,
            "is_unique": is_unique,
            "index_method": method or "",
            "columns": columns,
        }
    )


def schema_snapshot_fingerprint(snapshot: SchemaSnapshot) -> str:
    payload = {
        "db_type": snapshot.db_type,
        "database_name": snapshot.database_name,
        "schema_name": snapshot.schema_name,
        "tables": sorted(
            [
                {
                    "schema": t.schema_name,
                    "name": t.table_name,
                    "type": t.table_type,
                    "comment": t.table_comment or "",
                }
                for t in snapshot.tables
            ],
            key=lambda x: (x["schema"], x["name"]),
        ),
        "columns": sorted(
            [
                {
                    "schema": c.schema_name,
                    "table": c.table_name,
                    "ordinal": c.ordinal_position,
                    "name": c.column_name,
                    "type": c.data_type,
                    "nullable": c.is_nullable,
                    "default": c.default_value or "",
                    "comment": c.column_comment or "",
                }
                for c in snapshot.columns
            ],
            key=lambda x: (x["schema"], x["table"], x["ordinal"]),
        ),
        "pks": sorted(
            [
                {
                    "schema": pk.schema_name,
                    "table": pk.table_name,
                    "name": pk.constraint_name,
                    "ordinal": pk.ordinal_position,
                    "column": pk.column_name,
                }
                for pk in snapshot.primary_keys
            ],
            key=lambda x: (x["schema"], x["table"], x["name"], x["ordinal"]),
        ),
        "uniques": sorted(
            [
                {
                    "schema": uq.schema_name,
                    "table": uq.table_name,
                    "name": uq.constraint_name,
                    "ordinal": uq.ordinal_position,
                    "column": uq.column_name,
                }
                for uq in snapshot.unique_constraints
            ],
            key=lambda x: (x["schema"], x["table"], x["name"], x["ordinal"]),
        ),
        "fks": sorted(
            [
                {
                    "source_schema": fk.schema_name,
                    "source": fk.source_table,
                    "name": fk.constraint_name,
                    "target_schema": fk.target_schema,
                    "target": fk.target_table,
                    "cols": [(c.source_column, c.target_column) for c in fk.columns],
                }
                for fk in snapshot.foreign_keys
            ],
            key=lambda x: (x["source_schema"], x["source"], x["name"]),
        ),
        "indexes": sorted(
            [
                {
                    "schema": ix.schema_name,
                    "table": ix.table_name,
                    "name": ix.index_name,
                    "unique": ix.is_unique,
                    "method": ix.index_method or "",
                    "cols": [c.column_name for c in ix.columns],
                }
                for ix in snapshot.indexes
            ],
            key=lambda x: (x["schema"], x["table"], x["name"]),
        ),
    }
    return fingerprint(payload)


def _group_key_columns(
    rows,
) -> dict[tuple[str, str, str], list]:
    """Group PK/UNIQUE column rows by (schema, table, constraint_name)."""
    grouped: dict[tuple[str, str, str], list] = defaultdict(list)
    for row in rows:
        key = (row.schema_name, row.table_name, row.constraint_name)
        grouped[key].append(row)
    for cols in grouped.values():
        cols.sort(key=lambda r: r.ordinal_position)
    return grouped


def _single_column_unique_keys(snapshot: SchemaSnapshot) -> set[tuple[str, str, str]]:
    """
    Columns that are unique by themselves.

    - single-column UNIQUE constraint
    - single-column unique index
    - single-column PRIMARY KEY

    Composite PK/UNIQUE member columns are intentionally excluded.
    """
    alone: set[tuple[str, str, str]] = set()

    for _key, cols in _group_key_columns(snapshot.unique_constraints).items():
        if len(cols) == 1:
            c = cols[0]
            alone.add((c.schema_name, c.table_name, c.column_name))

    for _key, cols in _group_key_columns(snapshot.primary_keys).items():
        if len(cols) == 1:
            c = cols[0]
            alone.add((c.schema_name, c.table_name, c.column_name))

    for ix in snapshot.indexes:
        if ix.is_unique and len(ix.columns) == 1:
            alone.add((ix.schema_name, ix.table_name, ix.columns[0].column_name))

    return alone


class CatalogWriter:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_snapshot(self, *, source_id: int, run_id: int, snapshot: SchemaSnapshot) -> None:
        now = _utcnow()
        pk_cols: set[tuple[str, str, str]] = {
            (pk.schema_name, pk.table_name, pk.column_name) for pk in snapshot.primary_keys
        }
        alone_unique = _single_column_unique_keys(snapshot)

        seen_table_ids: set[int] = set()
        # Prefer (schema_name, table_name) keys for future multi-schema support.
        table_id_by_key: dict[tuple[str, str], int] = {}
        column_id_by_key: dict[tuple[str, str, str], int] = {}

        for table in snapshot.tables:
            fp = table_fp(table.schema_name, table.table_name, table.table_type, table.table_comment)
            existing = self.session.scalar(
                select(CatalogTable).where(
                    CatalogTable.source_id == source_id,
                    CatalogTable.schema_name == table.schema_name,
                    CatalogTable.table_name == table.table_name,
                )
            )
            if existing is None:
                existing = CatalogTable(
                    source_id=source_id,
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    table_type=table.table_type,
                    table_comment=table.table_comment,
                    object_fingerprint=fp,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_run_id=run_id,
                    active=True,
                )
                self.session.add(existing)
                self.session.flush()
            else:
                existing.table_type = table.table_type
                existing.table_comment = table.table_comment
                existing.object_fingerprint = fp
                existing.last_seen_at = now
                existing.last_run_id = run_id
                existing.active = True
            table_id_by_key[(table.schema_name, table.table_name)] = existing.id
            seen_table_ids.add(existing.id)

        seen_column_ids: set[int] = set()
        cols_by_table: dict[tuple[str, str], list] = defaultdict(list)
        for col in snapshot.columns:
            cols_by_table[(col.schema_name, col.table_name)].append(col)

        for (schema_name, table_name), cols in cols_by_table.items():
            table_id = table_id_by_key.get((schema_name, table_name))
            if table_id is None:
                continue
            for col in cols:
                is_pk = (schema_name, table_name, col.column_name) in pk_cols
                # is_unique means "this column alone is unique" — never mark
                # composite PK/UNIQUE members as individually unique.
                is_uq = (schema_name, table_name, col.column_name) in alone_unique
                fp = column_fp(
                    col.schema_name,
                    col.table_name,
                    col.ordinal_position,
                    col.column_name,
                    col.data_type,
                    col.is_nullable,
                    col.default_value,
                    col.column_comment,
                )
                existing = self.session.scalar(
                    select(CatalogColumn).where(
                        CatalogColumn.table_id == table_id,
                        CatalogColumn.column_name == col.column_name,
                    )
                )
                if existing is None:
                    existing = CatalogColumn(
                        table_id=table_id,
                        ordinal_position=col.ordinal_position,
                        column_name=col.column_name,
                        data_type=col.data_type,
                        character_maximum_length=col.character_maximum_length,
                        numeric_precision=col.numeric_precision,
                        numeric_scale=col.numeric_scale,
                        is_nullable=col.is_nullable,
                        default_value=col.default_value,
                        column_comment=col.column_comment,
                        is_primary_key=is_pk,
                        is_unique=is_uq,
                        object_fingerprint=fp,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_run_id=run_id,
                        active=True,
                    )
                    self.session.add(existing)
                    self.session.flush()
                else:
                    existing.ordinal_position = col.ordinal_position
                    existing.data_type = col.data_type
                    existing.character_maximum_length = col.character_maximum_length
                    existing.numeric_precision = col.numeric_precision
                    existing.numeric_scale = col.numeric_scale
                    existing.is_nullable = col.is_nullable
                    existing.default_value = col.default_value
                    existing.column_comment = col.column_comment
                    existing.is_primary_key = is_pk
                    existing.is_unique = is_uq
                    existing.object_fingerprint = fp
                    existing.last_seen_at = now
                    existing.last_run_id = run_id
                    existing.active = True
                column_id_by_key[(schema_name, table_name, col.column_name)] = existing.id
                seen_column_ids.add(existing.id)

        # Persist PRIMARY KEY / UNIQUE constraints with ordinal column order.
        seen_key_ids: set[int] = set()
        key_specs: list[tuple[str, dict[tuple[str, str, str], list]]] = [
            ("PRIMARY_KEY", _group_key_columns(snapshot.primary_keys)),
            ("UNIQUE", _group_key_columns(snapshot.unique_constraints)),
        ]
        for constraint_type, groups in key_specs:
            for (schema_name, table_name, constraint_name), cols in groups.items():
                table_id = table_id_by_key.get((schema_name, table_name))
                if table_id is None:
                    continue
                col_names = [c.column_name for c in cols]
                fp = key_constraint_fp(
                    schema_name, table_name, constraint_name, constraint_type, col_names
                )
                existing = self.session.scalar(
                    select(CatalogKeyConstraint).where(
                        CatalogKeyConstraint.table_id == table_id,
                        CatalogKeyConstraint.constraint_name == constraint_name,
                    )
                )
                if existing is None:
                    existing = CatalogKeyConstraint(
                        table_id=table_id,
                        constraint_name=constraint_name,
                        constraint_type=constraint_type,
                        object_fingerprint=fp,
                        first_seen_at=now,
                        last_seen_at=now,
                        last_run_id=run_id,
                        active=True,
                    )
                    self.session.add(existing)
                    self.session.flush()
                else:
                    existing.constraint_type = constraint_type
                    existing.object_fingerprint = fp
                    existing.last_seen_at = now
                    existing.last_run_id = run_id
                    existing.active = True
                    for old in list(existing.columns):
                        self.session.delete(old)
                    self.session.flush()

                for col in cols:
                    col_id = column_id_by_key.get((schema_name, table_name, col.column_name))
                    if col_id is None:
                        continue
                    self.session.add(
                        CatalogKeyConstraintColumn(
                            constraint_id=existing.id,
                            ordinal_position=col.ordinal_position,
                            column_id=col_id,
                        )
                    )
                seen_key_ids.add(existing.id)

        seen_relation_ids: set[int] = set()
        for fk in snapshot.foreign_keys:
            src_id = table_id_by_key.get((fk.schema_name, fk.source_table))
            tgt_id = table_id_by_key.get((fk.target_schema, fk.target_table))
            if src_id is None or tgt_id is None:
                continue
            mappings = [(c.source_column, c.target_column) for c in fk.columns]
            fp = relation_fp(
                source_schema=fk.schema_name,
                source_table=fk.source_table,
                constraint_name=fk.constraint_name,
                target_schema=fk.target_schema,
                target_table=fk.target_table,
                mappings=mappings,
            )
            existing = self.session.scalar(
                select(CatalogRelation).where(
                    CatalogRelation.source_table_id == src_id,
                    CatalogRelation.constraint_name == fk.constraint_name,
                )
            )
            if existing is None:
                existing = CatalogRelation(
                    source_id=source_id,
                    constraint_name=fk.constraint_name,
                    source_table_id=src_id,
                    target_table_id=tgt_id,
                    relation_type="FOREIGN_KEY",
                    object_fingerprint=fp,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_run_id=run_id,
                    active=True,
                )
                self.session.add(existing)
                self.session.flush()
            else:
                existing.source_id = source_id
                existing.source_table_id = src_id
                existing.target_table_id = tgt_id
                existing.object_fingerprint = fp
                existing.last_seen_at = now
                existing.last_run_id = run_id
                existing.active = True
                for old in list(existing.columns):
                    self.session.delete(old)
                self.session.flush()

            for col in fk.columns:
                src_col_id = column_id_by_key.get(
                    (fk.schema_name, fk.source_table, col.source_column)
                )
                tgt_col_id = column_id_by_key.get(
                    (fk.target_schema, fk.target_table, col.target_column)
                )
                if src_col_id is None or tgt_col_id is None:
                    continue
                self.session.add(
                    CatalogRelationColumn(
                        relation_id=existing.id,
                        ordinal_position=col.ordinal_position,
                        source_column_id=src_col_id,
                        target_column_id=tgt_col_id,
                    )
                )
            seen_relation_ids.add(existing.id)

        seen_index_ids: set[int] = set()
        for ix in snapshot.indexes:
            table_id = table_id_by_key.get((ix.schema_name, ix.table_name))
            if table_id is None:
                continue
            col_names = [c.column_name for c in ix.columns]
            fp = index_fp(
                ix.schema_name,
                ix.table_name,
                ix.index_name,
                ix.is_unique,
                ix.index_method,
                col_names,
            )
            existing = self.session.scalar(
                select(CatalogIndex).where(
                    CatalogIndex.table_id == table_id,
                    CatalogIndex.index_name == ix.index_name,
                )
            )
            if existing is None:
                existing = CatalogIndex(
                    table_id=table_id,
                    index_name=ix.index_name,
                    is_unique=ix.is_unique,
                    index_method=ix.index_method,
                    index_definition=ix.index_definition,
                    object_fingerprint=fp,
                    first_seen_at=now,
                    last_seen_at=now,
                    last_run_id=run_id,
                    active=True,
                )
                self.session.add(existing)
                self.session.flush()
            else:
                existing.is_unique = ix.is_unique
                existing.index_method = ix.index_method
                existing.index_definition = ix.index_definition
                existing.object_fingerprint = fp
                existing.last_seen_at = now
                existing.last_run_id = run_id
                existing.active = True
                for old in list(existing.columns):
                    self.session.delete(old)
                self.session.flush()

            for col in ix.columns:
                self.session.add(
                    CatalogIndexColumn(
                        index_id=existing.id,
                        ordinal_position=col.ordinal_position,
                        column_name=col.column_name,
                    )
                )
            seen_index_ids.add(existing.id)

        tables = self.session.scalars(
            select(CatalogTable).where(CatalogTable.source_id == source_id, CatalogTable.active.is_(True))
        ).all()
        for table in tables:
            if table.id not in seen_table_ids:
                table.active = False
                table.last_run_id = run_id
            for col in table.columns:
                if col.active and col.id not in seen_column_ids:
                    col.active = False
                    col.last_run_id = run_id
            for ix in table.indexes:
                if ix.active and ix.id not in seen_index_ids:
                    ix.active = False
                    ix.last_run_id = run_id
            for kc in table.key_constraints:
                if kc.active and kc.id not in seen_key_ids:
                    kc.active = False
                    kc.last_run_id = run_id

        relations = self.session.scalars(
            select(CatalogRelation).where(
                CatalogRelation.source_id == source_id, CatalogRelation.active.is_(True)
            )
        ).all()
        for rel in relations:
            if rel.id not in seen_relation_ids:
                rel.active = False
                rel.last_run_id = run_id

        self.session.flush()
