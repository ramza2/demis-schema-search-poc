"""Rule-based deterministic Search Document builder (no LLM)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import (
    CatalogColumn,
    CatalogKeyConstraint,
    CatalogRelation,
    CatalogSearchDocument,
    CatalogSource,
    CatalogTable,
)
from app.services.fingerprint import fingerprint

BUILDER_VERSION = "1.0.0"


@dataclass(frozen=True)
class BuiltDocument:
    document_key: str
    object_type: str
    table_id: int
    column_id: int | None
    searchable_text: str
    source_fingerprint: str
    document_fingerprint: str
    builder_version: str


@dataclass
class RebuildStats:
    source: str
    tables: int = 0
    columns: int = 0
    documents: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deactivated: int = 0


def table_document_key(source_id: int, schema_name: str, table_name: str) -> str:
    return f"table:{source_id}:{schema_name}:{table_name}"


def column_document_key(
    source_id: int, schema_name: str, table_name: str, column_name: str
) -> str:
    return f"column:{source_id}:{schema_name}:{table_name}:{column_name}"


def document_fingerprint_for(
    *,
    document_key: str,
    searchable_text: str,
    builder_version: str = BUILDER_VERSION,
) -> str:
    return fingerprint(
        {
            "document_key": document_key,
            "searchable_text": searchable_text,
            "builder_version": builder_version,
        }
    )


def _fmt_comment(value: str | None) -> str:
    return "" if value is None else value.strip()


def build_table_searchable_text(
    *,
    schema_name: str,
    table_name: str,
    table_comment: str | None,
    columns: list[dict[str, Any]],
    primary_key_columns: list[str],
    unique_constraints: list[dict[str, Any]],
    foreign_keys: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "Object Type: TABLE",
        f"Schema: {schema_name}",
        f"Table: {table_name}",
        f"Description: {_fmt_comment(table_comment)}",
        "",
        "Columns:",
    ]
    for col in columns:
        lines.append(f"- {col['name']}: {_fmt_comment(col.get('comment'))}")

    lines.extend(["", "Primary Key:"])
    if primary_key_columns:
        lines.extend(f"- {name}" for name in primary_key_columns)
    else:
        lines.append("- (none)")

    lines.extend(["", "Unique Constraints:"])
    if unique_constraints:
        for uc in unique_constraints:
            lines.append(f"- {uc['name']}: {', '.join(uc['columns'])}")
    else:
        lines.append("- (none)")

    lines.extend(["", "Foreign Keys:"])
    if foreign_keys:
        for fk in foreign_keys:
            src = ", ".join(fk["source_columns"])
            tgt = ", ".join(fk["target_columns"])
            lines.append(
                f"- {src} -> {fk['target_schema']}.{fk['target_table']}.{tgt}"
            )
    else:
        lines.append("- (none)")

    return "\n".join(lines) + "\n"


def build_column_searchable_text(
    *,
    schema_name: str,
    table_name: str,
    table_comment: str | None,
    column_name: str,
    column_comment: str | None,
    data_type: str,
    is_primary_key: bool,
    is_unique: bool,
    foreign_keys: list[dict[str, Any]],
) -> str:
    lines: list[str] = [
        "Object Type: COLUMN",
        f"Schema: {schema_name}",
        f"Table: {table_name}",
        f"Table Description: {_fmt_comment(table_comment)}",
        "",
        f"Column: {column_name}",
        f"Column Description: {_fmt_comment(column_comment)}",
        f"Data Type: {data_type}",
        f"Primary Key: {'true' if is_primary_key else 'false'}",
        f"Unique: {'true' if is_unique else 'false'}",
        "",
        "Foreign Key:",
    ]
    if foreign_keys:
        for fk in foreign_keys:
            tgt = ", ".join(fk["target_columns"])
            lines.append(f"- {fk['target_schema']}.{fk['target_table']}.{tgt}")
    else:
        lines.append("- (none)")

    return "\n".join(lines) + "\n"


class SearchDocumentBuilder:
    """Build / upsert TABLE and COLUMN search documents from raw catalog."""

    def __init__(self, session: Session, *, builder_version: str = BUILDER_VERSION) -> None:
        self.session = session
        self.builder_version = builder_version

    def rebuild_for_source(self, source_name: str = "medical_demo") -> RebuildStats:
        source = self.session.scalar(
            select(CatalogSource).where(CatalogSource.source_name == source_name)
        )
        if source is None:
            raise ValueError(f"catalog source not found: {source_name}")

        tables = list(
            self.session.scalars(
                select(CatalogTable)
                .where(CatalogTable.source_id == source.id, CatalogTable.active.is_(True))
                .options(
                    selectinload(CatalogTable.columns),
                    selectinload(CatalogTable.key_constraints).selectinload(
                        CatalogKeyConstraint.columns
                    ),
                )
                .order_by(CatalogTable.schema_name, CatalogTable.table_name)
            ).all()
        )

        relations = list(
            self.session.scalars(
                select(CatalogRelation)
                .where(
                    CatalogRelation.source_id == source.id,
                    CatalogRelation.active.is_(True),
                )
                .options(selectinload(CatalogRelation.columns))
            ).all()
        )

        table_by_id = {t.id: t for t in tables}
        related_ids = {r.target_table_id for r in relations} | {
            r.source_table_id for r in relations
        }
        missing_table_ids = related_ids - set(table_by_id)
        if missing_table_ids:
            for t in self.session.scalars(
                select(CatalogTable).where(CatalogTable.id.in_(missing_table_ids))
            ).all():
                table_by_id[t.id] = t

        column_by_id: dict[int, CatalogColumn] = {}
        for t in tables:
            for c in t.columns:
                column_by_id[c.id] = c

        needed_col_ids: set[int] = set()
        for rel in relations:
            for rc in rel.columns:
                needed_col_ids.add(rc.source_column_id)
                needed_col_ids.add(rc.target_column_id)
        missing_cols = needed_col_ids - set(column_by_id)
        if missing_cols:
            for c in self.session.scalars(
                select(CatalogColumn).where(CatalogColumn.id.in_(missing_cols))
            ).all():
                column_by_id[c.id] = c

        built: list[BuiltDocument] = []
        now = datetime.now(timezone.utc)

        for table in tables:
            active_cols = sorted(
                [c for c in table.columns if c.active],
                key=lambda c: c.ordinal_position,
            )
            pk_names, unique_constraints = self._key_constraint_views(table, column_by_id)
            table_fks = self._table_foreign_keys(
                table.id, relations, table_by_id, column_by_id
            )
            searchable = build_table_searchable_text(
                schema_name=table.schema_name,
                table_name=table.table_name,
                table_comment=table.table_comment,
                columns=[
                    {"name": c.column_name, "comment": c.column_comment}
                    for c in active_cols
                ],
                primary_key_columns=pk_names,
                unique_constraints=unique_constraints,
                foreign_keys=table_fks,
            )
            doc_key = table_document_key(source.id, table.schema_name, table.table_name)
            source_fp = fingerprint(
                {
                    "table": table.object_fingerprint,
                    "columns": [c.object_fingerprint for c in active_cols],
                    "key_constraints": [
                        kc.object_fingerprint
                        for kc in sorted(
                            [k for k in table.key_constraints if k.active],
                            key=lambda k: k.constraint_name,
                        )
                    ],
                    "foreign_keys": [
                        r.object_fingerprint
                        for r in sorted(
                            [rel for rel in relations if rel.source_table_id == table.id],
                            key=lambda r: r.constraint_name,
                        )
                    ],
                }
            )
            built.append(
                BuiltDocument(
                    document_key=doc_key,
                    object_type="TABLE",
                    table_id=table.id,
                    column_id=None,
                    searchable_text=searchable,
                    source_fingerprint=source_fp,
                    document_fingerprint=document_fingerprint_for(
                        document_key=doc_key,
                        searchable_text=searchable,
                        builder_version=self.builder_version,
                    ),
                    builder_version=self.builder_version,
                )
            )

            for col in active_cols:
                col_fks = self._column_foreign_keys(
                    table.id, col.id, relations, table_by_id, column_by_id
                )
                col_text = build_column_searchable_text(
                    schema_name=table.schema_name,
                    table_name=table.table_name,
                    table_comment=table.table_comment,
                    column_name=col.column_name,
                    column_comment=col.column_comment,
                    data_type=col.data_type,
                    is_primary_key=col.is_primary_key,
                    is_unique=col.is_unique,
                    foreign_keys=col_fks,
                )
                col_key = column_document_key(
                    source.id, table.schema_name, table.table_name, col.column_name
                )
                col_source_fp = fingerprint(
                    {
                        "column": col.object_fingerprint,
                        "table": table.object_fingerprint,
                        "foreign_keys": [
                            r.object_fingerprint
                            for r in sorted(
                                [
                                    rel
                                    for rel in relations
                                    if rel.source_table_id == table.id
                                    and any(
                                        rc.source_column_id == col.id for rc in rel.columns
                                    )
                                ],
                                key=lambda r: r.constraint_name,
                            )
                        ],
                    }
                )
                built.append(
                    BuiltDocument(
                        document_key=col_key,
                        object_type="COLUMN",
                        table_id=table.id,
                        column_id=col.id,
                        searchable_text=col_text,
                        source_fingerprint=col_source_fp,
                        document_fingerprint=document_fingerprint_for(
                            document_key=col_key,
                            searchable_text=col_text,
                            builder_version=self.builder_version,
                        ),
                        builder_version=self.builder_version,
                    )
                )

        stats = RebuildStats(source=source_name)
        stats.tables = sum(1 for d in built if d.object_type == "TABLE")
        stats.columns = sum(1 for d in built if d.object_type == "COLUMN")
        stats.documents = len(built)

        existing = {
            d.document_key: d
            for d in self.session.scalars(
                select(CatalogSearchDocument).where(
                    CatalogSearchDocument.source_id == source.id
                )
            ).all()
        }
        seen_keys: set[str] = set()

        for item in built:
            seen_keys.add(item.document_key)
            row = existing.get(item.document_key)
            if row is None:
                self.session.add(
                    CatalogSearchDocument(
                        source_id=source.id,
                        object_type=item.object_type,
                        table_id=item.table_id,
                        column_id=item.column_id,
                        document_key=item.document_key,
                        searchable_text=item.searchable_text,
                        source_fingerprint=item.source_fingerprint,
                        document_fingerprint=item.document_fingerprint,
                        builder_version=item.builder_version,
                        active=True,
                        first_seen_at=now,
                        last_seen_at=now,
                        updated_at=now,
                    )
                )
                stats.created += 1
                continue

            changed = (
                row.searchable_text != item.searchable_text
                or row.document_fingerprint != item.document_fingerprint
                or row.source_fingerprint != item.source_fingerprint
                or row.builder_version != item.builder_version
                or row.object_type != item.object_type
                or row.table_id != item.table_id
                or row.column_id != item.column_id
                or not row.active
            )
            row.object_type = item.object_type
            row.table_id = item.table_id
            row.column_id = item.column_id
            row.searchable_text = item.searchable_text
            row.source_fingerprint = item.source_fingerprint
            row.document_fingerprint = item.document_fingerprint
            row.builder_version = item.builder_version
            row.active = True
            row.last_seen_at = now
            row.updated_at = now
            if changed:
                stats.updated += 1
            else:
                stats.unchanged += 1

        for key, row in existing.items():
            if key not in seen_keys and row.active:
                row.active = False
                row.updated_at = now
                stats.deactivated += 1

        self.session.flush()
        return stats

    def _key_constraint_views(
        self,
        table: CatalogTable,
        column_by_id: dict[int, CatalogColumn],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        pk_names: list[str] = []
        unique_constraints: list[dict[str, Any]] = []
        for kc in sorted(
            [k for k in table.key_constraints if k.active],
            key=lambda k: k.constraint_name,
        ):
            names = [
                column_by_id[cc.column_id].column_name
                for cc in sorted(kc.columns, key=lambda x: x.ordinal_position)
                if cc.column_id in column_by_id
            ]
            if kc.constraint_type == "PRIMARY_KEY":
                pk_names = names
            elif kc.constraint_type == "UNIQUE":
                unique_constraints.append({"name": kc.constraint_name, "columns": names})
        if not pk_names:
            pk_names = [
                c.column_name
                for c in sorted(
                    [c for c in table.columns if c.active and c.is_primary_key],
                    key=lambda c: c.ordinal_position,
                )
            ]
        return pk_names, unique_constraints

    def _table_foreign_keys(
        self,
        table_id: int,
        relations: list[CatalogRelation],
        table_by_id: dict[int, CatalogTable],
        column_by_id: dict[int, CatalogColumn],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for rel in sorted(
            [r for r in relations if r.source_table_id == table_id],
            key=lambda r: r.constraint_name,
        ):
            tgt_table = table_by_id.get(rel.target_table_id)
            src_cols: list[str] = []
            tgt_cols: list[str] = []
            for rc in sorted(rel.columns, key=lambda x: x.ordinal_position):
                sc = column_by_id.get(rc.source_column_id)
                tc = column_by_id.get(rc.target_column_id)
                if sc:
                    src_cols.append(sc.column_name)
                if tc:
                    tgt_cols.append(tc.column_name)
            result.append(
                {
                    "constraint_name": rel.constraint_name,
                    "source_columns": src_cols,
                    "target_schema": tgt_table.schema_name if tgt_table else "",
                    "target_table": tgt_table.table_name if tgt_table else "",
                    "target_columns": tgt_cols,
                }
            )
        return result

    def _column_foreign_keys(
        self,
        table_id: int,
        column_id: int,
        relations: list[CatalogRelation],
        table_by_id: dict[int, CatalogTable],
        column_by_id: dict[int, CatalogColumn],
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for rel in sorted(
            [r for r in relations if r.source_table_id == table_id],
            key=lambda r: r.constraint_name,
        ):
            if not any(rc.source_column_id == column_id for rc in rel.columns):
                continue
            tgt_table = table_by_id.get(rel.target_table_id)
            tgt_cols = [
                column_by_id[rc.target_column_id].column_name
                for rc in sorted(rel.columns, key=lambda x: x.ordinal_position)
                if rc.target_column_id in column_by_id
            ]
            result.append(
                {
                    "constraint_name": rel.constraint_name,
                    "target_schema": tgt_table.schema_name if tgt_table else "",
                    "target_table": tgt_table.table_name if tgt_table else "",
                    "target_columns": tgt_cols,
                }
            )
        return result
