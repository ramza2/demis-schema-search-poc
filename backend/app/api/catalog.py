"""Catalog Category management APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.models.catalog import CatalogSource, CatalogTable
from app.models.catalog_category import CatalogCategory, CatalogTableCategory
from app.schemas.catalog_api import (
    CategoryCreate,
    CategoryOut,
    CategoryTableOut,
    CategoryUpdate,
    TableCategoryOut,
    TableCategoryReplace,
)

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _category_out(session, category: CatalogCategory) -> CategoryOut:
    table_count = session.scalar(
        select(func.count())
        .select_from(CatalogTableCategory)
        .join(CatalogTable, CatalogTable.id == CatalogTableCategory.table_id)
        .where(
            CatalogTableCategory.category_id == category.id,
            CatalogTable.active.is_(True),
        )
    )
    return CategoryOut(
        id=category.id,
        source_id=category.source_id,
        category_key=category.category_key,
        category_name=category.category_name,
        description=category.description,
        sort_order=category.sort_order,
        active=category.active,
        table_count=int(table_count or 0),
    )


def _table_categories(session, table_id: int) -> list[TableCategoryOut]:
    rows = session.execute(
        select(CatalogTableCategory, CatalogCategory)
        .join(CatalogCategory, CatalogCategory.id == CatalogTableCategory.category_id)
        .where(CatalogTableCategory.table_id == table_id)
        .order_by(
            CatalogTableCategory.is_primary.desc(),
            CatalogCategory.sort_order,
            CatalogCategory.category_name,
        )
    ).all()
    return [
        TableCategoryOut(
            category_id=category.id,
            category_key=category.category_key,
            category_name=category.category_name,
            is_primary=mapping.is_primary,
            assignment_source=mapping.assignment_source,
            confidence=mapping.confidence,
            note=mapping.note,
        )
        for mapping, category in rows
    ]


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(
    source_id: int = Query(..., gt=0),
    active: bool | None = True,
) -> list[CategoryOut]:
    session = _session()
    try:
        if session.get(CatalogSource, source_id) is None:
            raise HTTPException(status_code=404, detail="catalog source not found")
        stmt = select(CatalogCategory).where(CatalogCategory.source_id == source_id)
        if active is not None:
            stmt = stmt.where(CatalogCategory.active.is_(active))
        categories = session.scalars(
            stmt.order_by(CatalogCategory.sort_order, CatalogCategory.category_name)
        ).all()
        return [_category_out(session, category) for category in categories]
    finally:
        session.close()


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate) -> CategoryOut:
    session = _session()
    try:
        if session.get(CatalogSource, payload.source_id) is None:
            raise HTTPException(status_code=404, detail="catalog source not found")
        category = CatalogCategory(
            source_id=payload.source_id,
            category_key=payload.category_key,
            category_name=payload.category_name.strip(),
            description=payload.description,
            sort_order=payload.sort_order,
            active=payload.active,
        )
        session.add(category)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="category_key already exists for this source",
            ) from exc
        session.refresh(category)
        return _category_out(session, category)
    finally:
        session.close()


@router.put("/categories/{category_id}", response_model=CategoryOut)
def update_category(category_id: int, payload: CategoryUpdate) -> CategoryOut:
    session = _session()
    try:
        category = session.get(CatalogCategory, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="category not found")
        changes = payload.model_dump(exclude_unset=True)
        if "category_name" in changes:
            category.category_name = str(changes["category_name"]).strip()
        if "description" in changes:
            category.description = changes["description"]
        if "sort_order" in changes:
            category.sort_order = int(changes["sort_order"])
        if "active" in changes:
            category.active = bool(changes["active"])
        session.commit()
        session.refresh(category)
        return _category_out(session, category)
    finally:
        session.close()


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: int) -> Response:
    session = _session()
    try:
        category = session.get(CatalogCategory, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="category not found")
        session.delete(category)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        session.close()


@router.get("/categories/{category_id}/tables", response_model=list[CategoryTableOut])
def list_category_tables(category_id: int) -> list[CategoryTableOut]:
    session = _session()
    try:
        category = session.get(CatalogCategory, category_id)
        if category is None:
            raise HTTPException(status_code=404, detail="category not found")
        rows = session.execute(
            select(CatalogTableCategory, CatalogTable)
            .join(CatalogTable, CatalogTable.id == CatalogTableCategory.table_id)
            .where(
                CatalogTableCategory.category_id == category_id,
                CatalogTable.active.is_(True),
            )
            .order_by(CatalogTable.schema_name, CatalogTable.table_name)
        ).all()
        return [
            CategoryTableOut(
                table_id=table.id,
                schema_name=table.schema_name,
                table_name=table.table_name,
                table_comment=table.table_comment,
                is_primary=mapping.is_primary,
                assignment_source=mapping.assignment_source,
                confidence=mapping.confidence,
            )
            for mapping, table in rows
        ]
    finally:
        session.close()


@router.get("/tables/{table_id}/categories", response_model=list[TableCategoryOut])
def list_table_categories(table_id: int) -> list[TableCategoryOut]:
    session = _session()
    try:
        if session.get(CatalogTable, table_id) is None:
            raise HTTPException(status_code=404, detail="table not found")
        return _table_categories(session, table_id)
    finally:
        session.close()


@router.put("/tables/{table_id}/categories", response_model=list[TableCategoryOut])
def replace_table_categories(
    table_id: int,
    payload: TableCategoryReplace,
) -> list[TableCategoryOut]:
    session = _session()
    try:
        table = session.get(CatalogTable, table_id)
        if table is None:
            raise HTTPException(status_code=404, detail="table not found")

        category_ids = [item.category_id for item in payload.assignments]
        if len(category_ids) != len(set(category_ids)):
            raise HTTPException(status_code=400, detail="duplicate category_id")
        if sum(1 for item in payload.assignments if item.is_primary) > 1:
            raise HTTPException(status_code=400, detail="only one primary category is allowed")

        categories: dict[int, CatalogCategory] = {}
        if category_ids:
            found = session.scalars(
                select(CatalogCategory).where(CatalogCategory.id.in_(category_ids))
            ).all()
            categories = {int(category.id): category for category in found}
            missing = sorted(set(category_ids) - set(categories))
            if missing:
                raise HTTPException(status_code=404, detail=f"category not found: {missing}")
            wrong_source = sorted(
                category_id
                for category_id, category in categories.items()
                if int(category.source_id) != int(table.source_id)
            )
            if wrong_source:
                raise HTTPException(
                    status_code=400,
                    detail=f"category belongs to a different source: {wrong_source}",
                )
            inactive = sorted(
                category_id
                for category_id, category in categories.items()
                if not category.active
            )
            if inactive:
                raise HTTPException(status_code=400, detail=f"inactive category: {inactive}")

        session.execute(
            delete(CatalogTableCategory).where(CatalogTableCategory.table_id == table_id)
        )
        for item in payload.assignments:
            session.add(
                CatalogTableCategory(
                    table_id=table_id,
                    category_id=item.category_id,
                    is_primary=item.is_primary,
                    assignment_source=item.assignment_source,
                    confidence=item.confidence,
                    note=item.note,
                )
            )
        session.commit()
        return _table_categories(session, table_id)
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
