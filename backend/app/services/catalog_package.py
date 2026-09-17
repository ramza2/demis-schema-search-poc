"""Build a portable DEMIS Catalog Package from analyzed catalog metadata."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import (
    CatalogAnalysisRun,
    CatalogColumn,
    CatalogIndex,
    CatalogIndexColumn,
    CatalogKeyConstraint,
    CatalogKeyConstraintColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogSource,
    CatalogTable,
)
from app.models.catalog_category import CatalogCategory, CatalogTableCategory


PACKAGE_ROOT = "demis_catalog_package"
PACKAGE_FORMAT = "demis-catalog-package"
PACKAGE_VERSION = "1.0"


@dataclass(frozen=True)
class CatalogPackageResult:
    filename: str
    content: bytes
    manifest: dict[str, Any]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _table_key(table: CatalogTable) -> str:
    return f"{table.schema_name}.{table.table_name}"


def _column_key(table: CatalogTable, column: CatalogColumn) -> str:
    return f"{_table_key(table)}.{column.column_name}"


def build_catalog_package(session: Session, source_id: int) -> CatalogPackageResult:
    source = session.get(CatalogSource, source_id)
    if source is None:
        raise LookupError("catalog source not found")

    tables = session.scalars(
        select(CatalogTable)
        .where(CatalogTable.source_id == source_id, CatalogTable.active.is_(True))
        .order_by(CatalogTable.schema_name, CatalogTable.table_name)
    ).all()
    table_by_id = {int(table.id): table for table in tables}
    table_ids = list(table_by_id)

    columns = []
    relations = []
    indexes = []
    constraints = []
    if table_ids:
        columns = session.scalars(
            select(CatalogColumn)
            .where(CatalogColumn.table_id.in_(table_ids), CatalogColumn.active.is_(True))
            .order_by(CatalogColumn.table_id, CatalogColumn.ordinal_position)
        ).all()
        relations = session.scalars(
            select(CatalogRelation)
            .where(CatalogRelation.source_id == source_id, CatalogRelation.active.is_(True))
            .order_by(CatalogRelation.constraint_name, CatalogRelation.id)
        ).all()
        indexes = session.scalars(
            select(CatalogIndex)
            .where(CatalogIndex.table_id.in_(table_ids), CatalogIndex.active.is_(True))
            .order_by(CatalogIndex.table_id, CatalogIndex.index_name)
        ).all()
        constraints = session.scalars(
            select(CatalogKeyConstraint)
            .where(
                CatalogKeyConstraint.table_id.in_(table_ids),
                CatalogKeyConstraint.active.is_(True),
            )
            .order_by(CatalogKeyConstraint.table_id, CatalogKeyConstraint.constraint_name)
        ).all()

    column_by_id = {int(column.id): column for column in columns}

    constraint_columns: dict[int, list[CatalogKeyConstraintColumn]] = {}
    constraint_ids = [int(item.id) for item in constraints]
    if constraint_ids:
        rows = session.scalars(
            select(CatalogKeyConstraintColumn)
            .where(CatalogKeyConstraintColumn.constraint_id.in_(constraint_ids))
            .order_by(
                CatalogKeyConstraintColumn.constraint_id,
                CatalogKeyConstraintColumn.ordinal_position,
            )
        ).all()
        for row in rows:
            constraint_columns.setdefault(int(row.constraint_id), []).append(row)

    index_columns: dict[int, list[CatalogIndexColumn]] = {}
    index_ids = [int(item.id) for item in indexes]
    if index_ids:
        rows = session.scalars(
            select(CatalogIndexColumn)
            .where(CatalogIndexColumn.index_id.in_(index_ids))
            .order_by(CatalogIndexColumn.index_id, CatalogIndexColumn.ordinal_position)
        ).all()
        for row in rows:
            index_columns.setdefault(int(row.index_id), []).append(row)

    relation_columns: dict[int, list[CatalogRelationColumn]] = {}
    relation_ids = [int(item.id) for item in relations]
    if relation_ids:
        rows = session.scalars(
            select(CatalogRelationColumn)
            .where(CatalogRelationColumn.relation_id.in_(relation_ids))
            .order_by(CatalogRelationColumn.relation_id, CatalogRelationColumn.ordinal_position)
        ).all()
        for row in rows:
            relation_columns.setdefault(int(row.relation_id), []).append(row)

    categories = session.scalars(
        select(CatalogCategory)
        .where(CatalogCategory.source_id == source_id)
        .order_by(CatalogCategory.sort_order, CatalogCategory.category_name)
    ).all()
    category_by_id = {int(category.id): category for category in categories}

    mappings: list[CatalogTableCategory] = []
    if table_ids and category_by_id:
        mappings = session.scalars(
            select(CatalogTableCategory)
            .where(
                CatalogTableCategory.table_id.in_(table_ids),
                CatalogTableCategory.category_id.in_(list(category_by_id)),
            )
            .order_by(CatalogTableCategory.table_id, CatalogTableCategory.is_primary.desc())
        ).all()

    categories_by_table: dict[int, list[str]] = {}
    for mapping in mappings:
        category = category_by_id.get(int(mapping.category_id))
        if category is not None:
            categories_by_table.setdefault(int(mapping.table_id), []).append(category.category_key)

    latest_run = session.scalar(
        select(CatalogAnalysisRun)
        .where(CatalogAnalysisRun.source_id == source_id)
        .order_by(CatalogAnalysisRun.id.desc())
        .limit(1)
    )

    constraints_by_table: dict[int, list[dict[str, Any]]] = {}
    for constraint in constraints:
        col_names = []
        for item in constraint_columns.get(int(constraint.id), []):
            column = column_by_id.get(int(item.column_id))
            if column is not None:
                col_names.append(column.column_name)
        constraints_by_table.setdefault(int(constraint.table_id), []).append(
            {
                "constraint_name": constraint.constraint_name,
                "constraint_type": constraint.constraint_type,
                "columns": col_names,
            }
        )

    database_payload = {
        "source": {
            "source_name": source.source_name,
            "db_type": source.db_type,
            "database_name": source.database_name,
            "default_schema": source.default_schema,
        },
        "latest_analysis": None
        if latest_run is None
        else {
            "run_id": int(latest_run.id),
            "status": latest_run.status,
            "target_schema": latest_run.target_schema,
            "started_at": _iso(latest_run.started_at),
            "finished_at": _iso(latest_run.finished_at),
            "schema_fingerprint": latest_run.schema_fingerprint,
            "counts": {
                "tables": latest_run.table_count,
                "columns": latest_run.column_count,
                "relations": latest_run.relation_count,
                "indexes": latest_run.index_count,
            },
        },
        "security": {
            "connection_host_exported": False,
            "username_exported": False,
            "credentials_exported": False,
            "connection_options_exported": False,
        },
    }

    tables_payload = {
        "tables": [
            {
                "table_key": _table_key(table),
                "schema_name": table.schema_name,
                "table_name": table.table_name,
                "table_type": table.table_type,
                "table_comment": table.table_comment,
                "comment_provenance": "DB_COMMENT" if table.table_comment else None,
                "object_fingerprint": table.object_fingerprint,
                "key_constraints": constraints_by_table.get(int(table.id), []),
                "categories": categories_by_table.get(int(table.id), []),
            }
            for table in tables
        ]
    }

    columns_payload = {
        "columns": [
            {
                "column_key": _column_key(table_by_id[int(column.table_id)], column),
                "table_key": _table_key(table_by_id[int(column.table_id)]),
                "ordinal_position": column.ordinal_position,
                "column_name": column.column_name,
                "data_type": column.data_type,
                "character_maximum_length": column.character_maximum_length,
                "numeric_precision": column.numeric_precision,
                "numeric_scale": column.numeric_scale,
                "nullable": column.is_nullable,
                "default_value": column.default_value,
                "column_comment": column.column_comment,
                "comment_provenance": "DB_COMMENT" if column.column_comment else None,
                "primary_key": column.is_primary_key,
                "unique": column.is_unique,
                "object_fingerprint": column.object_fingerprint,
            }
            for column in columns
            if int(column.table_id) in table_by_id
        ]
    }

    relation_items: list[dict[str, Any]] = []
    for relation in relations:
        source_table = table_by_id.get(int(relation.source_table_id))
        target_table = table_by_id.get(int(relation.target_table_id))
        if source_table is None or target_table is None:
            continue
        mappings_out = []
        for item in relation_columns.get(int(relation.id), []):
            source_col = column_by_id.get(int(item.source_column_id))
            target_col = column_by_id.get(int(item.target_column_id))
            if source_col is None or target_col is None:
                continue
            mappings_out.append(
                {
                    "ordinal_position": item.ordinal_position,
                    "source_column": source_col.column_name,
                    "target_column": target_col.column_name,
                }
            )
        relation_items.append(
            {
                "relation_key": f"{_table_key(source_table)}::{relation.constraint_name}",
                "constraint_name": relation.constraint_name,
                "relation_type": relation.relation_type,
                "source_table_key": _table_key(source_table),
                "target_table_key": _table_key(target_table),
                "column_mapping": mappings_out,
                "object_fingerprint": relation.object_fingerprint,
            }
        )
    relations_payload = {"relations": relation_items}

    indexes_payload = {
        "indexes": [
            {
                "index_key": f"{_table_key(table_by_id[int(index.table_id)])}::{index.index_name}",
                "table_key": _table_key(table_by_id[int(index.table_id)]),
                "index_name": index.index_name,
                "unique": index.is_unique,
                "index_method": index.index_method,
                "index_definition": index.index_definition,
                "columns": [
                    item.column_name for item in index_columns.get(int(index.id), [])
                ],
                "object_fingerprint": index.object_fingerprint,
            }
            for index in indexes
            if int(index.table_id) in table_by_id
        ]
    }

    categories_payload = {
        "categories": [
            {
                "category_key": category.category_key,
                "category_name": category.category_name,
                "description": category.description,
                "sort_order": category.sort_order,
                "active": category.active,
                "definition_provenance": "CATALOG_CATEGORY",
            }
            for category in categories
        ],
        "table_assignments": [
            {
                "table_key": _table_key(table_by_id[int(mapping.table_id)]),
                "category_key": category_by_id[int(mapping.category_id)].category_key,
                "is_primary": mapping.is_primary,
                "assignment_source": mapping.assignment_source,
                "confidence": mapping.confidence,
                "note": mapping.note,
            }
            for mapping in mappings
            if int(mapping.table_id) in table_by_id
            and int(mapping.category_id) in category_by_id
        ],
    }

    erd_payload = {
        "nodes": [
            {
                "id": _table_key(table),
                "schema_name": table.schema_name,
                "table_name": table.table_name,
                "label": table.table_comment or table.table_name,
                "categories": categories_by_table.get(int(table.id), []),
            }
            for table in tables
        ],
        "edges": [
            {
                "id": item["relation_key"],
                "source": item["source_table_key"],
                "target": item["target_table_key"],
                "constraint_name": item["constraint_name"],
                "relation_type": item["relation_type"],
            }
            for item in relation_items
        ],
    }

    payloads: dict[str, bytes] = {
        "database.json": _json_bytes(database_payload),
        "categories.json": _json_bytes(categories_payload),
        "tables.json": _json_bytes(tables_payload),
        "columns.json": _json_bytes(columns_payload),
        "relations.json": _json_bytes(relations_payload),
        "indexes.json": _json_bytes(indexes_payload),
        "erd.json": _json_bytes(erd_payload),
    }

    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "package_format": PACKAGE_FORMAT,
        "package_version": PACKAGE_VERSION,
        "generated_at": generated_at,
        "source": {
            "source_name": source.source_name,
            "db_type": source.db_type,
            "database_name": source.database_name,
            "default_schema": source.default_schema,
        },
        "schema_fingerprint": latest_run.schema_fingerprint if latest_run else None,
        "counts": {
            "tables": len(tables),
            "columns": len(columns),
            "relations": len(relation_items),
            "indexes": len(indexes),
            "categories": len(categories),
            "category_assignments": len(mappings),
        },
        "provenance_policy": {
            "physical_metadata": [
                "database.json",
                "tables.json",
                "columns.json",
                "relations.json",
                "indexes.json",
            ],
            "semantic_metadata": "categories.json",
            "semantic_assignment_source_values": ["MANUAL", "AUTO", "IMPORT"],
            "note": "Physical DB facts and semantic/category metadata are exported separately; category assignments retain source and confidence when available.",
        },
        "files": [
            {
                "path": name,
                "sha256": _sha256(content),
                "bytes": len(content),
            }
            for name, content in sorted(payloads.items())
        ],
    }
    manifest_bytes = _json_bytes(manifest)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{PACKAGE_ROOT}/manifest.json", manifest_bytes)
        for name, content in sorted(payloads.items()):
            archive.writestr(f"{PACKAGE_ROOT}/{name}", content)

    safe_source = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source.source_name
    )
    filename = f"demis_catalog_package_{safe_source}.zip"
    return CatalogPackageResult(filename=filename, content=buffer.getvalue(), manifest=manifest)
