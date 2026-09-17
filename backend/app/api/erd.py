"""Source-scoped ERD graph API for DEMIS Schema Analyzer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogSource,
    CatalogTable,
)
from app.models.catalog_category import CatalogCategory, CatalogTableCategory

router = APIRouter(prefix="/api/v1/schema", tags=["schema-erd"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _table_key(table: CatalogTable) -> str:
    return f"{table.schema_name}.{table.table_name}"


@router.get("/erd")
def get_erd_graph(source_id: int = Query(..., gt=0)) -> dict:
    """Return one Catalog Source as a compact, portable ERD graph."""
    session = _session()
    try:
        source = session.get(CatalogSource, source_id)
        if source is None:
            raise HTTPException(status_code=404, detail="catalog source not found")

        tables = session.scalars(
            select(CatalogTable)
            .where(CatalogTable.source_id == source_id, CatalogTable.active.is_(True))
            .order_by(CatalogTable.schema_name, CatalogTable.table_name)
        ).all()
        table_by_id = {int(table.id): table for table in tables}
        table_ids = list(table_by_id)

        categories = session.scalars(
            select(CatalogCategory)
            .where(CatalogCategory.source_id == source_id, CatalogCategory.active.is_(True))
            .order_by(CatalogCategory.sort_order, CatalogCategory.category_name)
        ).all()
        category_by_id = {int(category.id): category for category in categories}

        category_rows: list[CatalogTableCategory] = []
        if table_ids and category_by_id:
            category_rows = session.scalars(
                select(CatalogTableCategory)
                .where(
                    CatalogTableCategory.table_id.in_(table_ids),
                    CatalogTableCategory.category_id.in_(list(category_by_id)),
                )
                .order_by(CatalogTableCategory.table_id, CatalogTableCategory.is_primary.desc())
            ).all()

        categories_by_table: dict[int, list[dict]] = {}
        for mapping in category_rows:
            category = category_by_id.get(int(mapping.category_id))
            if category is None:
                continue
            categories_by_table.setdefault(int(mapping.table_id), []).append(
                {
                    "id": int(category.id),
                    "key": category.category_key,
                    "name": category.category_name,
                    "is_primary": bool(mapping.is_primary),
                    "assignment_source": mapping.assignment_source,
                    "confidence": mapping.confidence,
                }
            )

        relations: list[CatalogRelation] = []
        relation_columns: dict[int, list[CatalogRelationColumn]] = {}
        if table_ids:
            relations = session.scalars(
                select(CatalogRelation)
                .where(CatalogRelation.source_id == source_id, CatalogRelation.active.is_(True))
                .order_by(CatalogRelation.constraint_name, CatalogRelation.id)
            ).all()
            relation_ids = [int(relation.id) for relation in relations]
            if relation_ids:
                rows = session.scalars(
                    select(CatalogRelationColumn)
                    .where(CatalogRelationColumn.relation_id.in_(relation_ids))
                    .order_by(
                        CatalogRelationColumn.relation_id,
                        CatalogRelationColumn.ordinal_position,
                    )
                ).all()
                for row in rows:
                    relation_columns.setdefault(int(row.relation_id), []).append(row)

        column_ids = {
            int(item.source_column_id)
            for rows in relation_columns.values()
            for item in rows
        } | {
            int(item.target_column_id)
            for rows in relation_columns.values()
            for item in rows
        }
        column_by_id: dict[int, CatalogColumn] = {}
        if column_ids:
            columns = session.scalars(
                select(CatalogColumn).where(CatalogColumn.id.in_(list(column_ids)))
            ).all()
            column_by_id = {int(column.id): column for column in columns}

        nodes = [
            {
                "id": int(table.id),
                "table_key": _table_key(table),
                "schema_name": table.schema_name,
                "table_name": table.table_name,
                "table_type": table.table_type,
                "table_comment": table.table_comment,
                "categories": categories_by_table.get(int(table.id), []),
            }
            for table in tables
        ]

        edges: list[dict] = []
        for relation in relations:
            source_table = table_by_id.get(int(relation.source_table_id))
            target_table = table_by_id.get(int(relation.target_table_id))
            if source_table is None or target_table is None:
                continue
            mapping = []
            for item in relation_columns.get(int(relation.id), []):
                source_column = column_by_id.get(int(item.source_column_id))
                target_column = column_by_id.get(int(item.target_column_id))
                if source_column is None or target_column is None:
                    continue
                mapping.append(
                    {
                        "source": source_column.column_name,
                        "target": target_column.column_name,
                        "ordinal_position": item.ordinal_position,
                    }
                )
            edges.append(
                {
                    "id": int(relation.id),
                    "constraint": relation.constraint_name,
                    "relation_type": relation.relation_type,
                    "source_id": int(source_table.id),
                    "target_id": int(target_table.id),
                    "source_table_key": _table_key(source_table),
                    "target_table_key": _table_key(target_table),
                    "column_mapping": mapping,
                }
            )

        return {
            "source": {
                "id": int(source.id),
                "source_name": source.source_name,
                "db_type": source.db_type,
                "database_name": source.database_name,
                "default_schema": source.default_schema,
            },
            "counts": {
                "nodes": len(nodes),
                "edges": len(edges),
                "categories": len(categories),
            },
            "categories": [
                {
                    "id": int(category.id),
                    "key": category.category_key,
                    "name": category.category_name,
                    "description": category.description,
                    "sort_order": category.sort_order,
                }
                for category in categories
            ],
            "nodes": nodes,
            "edges": edges,
        }
    finally:
        session.close()
