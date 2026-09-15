"""Schema Analyzer / Catalog query APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogAnalysisRun,
    CatalogColumn,
    CatalogIndex,
    CatalogRelation,
    CatalogTable,
)
from app.schemas.schema_api import (
    AnalysisRunSummary,
    AnalyzeResponse,
    ColumnOut,
    IndexOut,
    RelationColumnMapping,
    RelationOut,
    TableDetail,
    TableSummary,
)
from app.services.schema_analysis import SchemaAnalysisService

router = APIRouter(prefix="/api/v1/schema", tags=["schema"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_schema() -> AnalyzeResponse:
    service = SchemaAnalysisService()
    run = service.analyze_medical_demo(schema_name="public")
    return AnalyzeResponse(
        run_id=run.id,
        status=run.status,
        source="medical_demo",
        schema_name=run.target_schema,
        tables=run.table_count,
        columns=run.column_count,
        relations=run.relation_count,
        indexes=run.index_count,
        schema_fingerprint=run.schema_fingerprint,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
    )


@router.get("/runs", response_model=list[AnalysisRunSummary])
def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[AnalysisRunSummary]:
    session = _session()
    try:
        rows = session.scalars(
            select(CatalogAnalysisRun).order_by(CatalogAnalysisRun.id.desc()).limit(limit)
        ).all()
        return [
            AnalysisRunSummary(
                id=r.id,
                source_id=r.source_id,
                status=r.status,
                target_schema=r.target_schema,
                started_at=r.started_at,
                finished_at=r.finished_at,
                table_count=r.table_count,
                column_count=r.column_count,
                relation_count=r.relation_count,
                index_count=r.index_count,
                schema_fingerprint=r.schema_fingerprint,
                error_message=r.error_message,
            )
            for r in rows
        ]
    finally:
        session.close()


@router.get("/runs/{run_id}", response_model=AnalysisRunSummary)
def get_run(run_id: int) -> AnalysisRunSummary:
    session = _session()
    try:
        run = session.get(CatalogAnalysisRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="analysis run not found")
        return AnalysisRunSummary(
            id=run.id,
            source_id=run.source_id,
            status=run.status,
            target_schema=run.target_schema,
            started_at=run.started_at,
            finished_at=run.finished_at,
            table_count=run.table_count,
            column_count=run.column_count,
            relation_count=run.relation_count,
            index_count=run.index_count,
            schema_fingerprint=run.schema_fingerprint,
            error_message=run.error_message,
        )
    finally:
        session.close()


@router.get("/tables", response_model=list[TableSummary])
def list_tables(
    schema_name: str | None = None,
    active: bool | None = True,
    name: str | None = None,
    source_id: int | None = None,
) -> list[TableSummary]:
    session = _session()
    try:
        stmt = select(CatalogTable)
        if source_id is not None:
            stmt = stmt.where(CatalogTable.source_id == source_id)
        if schema_name:
            stmt = stmt.where(CatalogTable.schema_name == schema_name)
        if active is not None:
            stmt = stmt.where(CatalogTable.active.is_(active))
        if name:
            stmt = stmt.where(CatalogTable.table_name.ilike(f"%{name.lower()}%"))
        stmt = stmt.order_by(CatalogTable.schema_name, CatalogTable.table_name)
        tables = session.scalars(stmt).all()
        result: list[TableSummary] = []
        for t in tables:
            col_count = session.scalar(
                select(func.count()).select_from(CatalogColumn).where(
                    CatalogColumn.table_id == t.id,
                    CatalogColumn.active.is_(True),
                )
            )
            result.append(
                TableSummary(
                    id=t.id,
                    schema_name=t.schema_name,
                    table_name=t.table_name,
                    table_type=t.table_type,
                    table_comment=t.table_comment,
                    active=t.active,
                    object_fingerprint=t.object_fingerprint,
                    column_count=int(col_count or 0),
                )
            )
        return result
    finally:
        session.close()


def _relation_out(session, rel: CatalogRelation) -> RelationOut:
    src_table = session.get(CatalogTable, rel.source_table_id)
    tgt_table = session.get(CatalogTable, rel.target_table_id)
    mappings: list[RelationColumnMapping] = []
    for rc in sorted(rel.columns, key=lambda x: x.ordinal_position):
        src_col = session.get(CatalogColumn, rc.source_column_id)
        tgt_col = session.get(CatalogColumn, rc.target_column_id)
        mappings.append(
            RelationColumnMapping(
                source=src_col.column_name if src_col else "",
                target=tgt_col.column_name if tgt_col else "",
                ordinal_position=rc.ordinal_position,
            )
        )
    return RelationOut(
        id=rel.id,
        constraint=rel.constraint_name,
        relation_type=rel.relation_type,
        source_table=src_table.table_name if src_table else "",
        target_table=tgt_table.table_name if tgt_table else "",
        column_mapping=mappings,
        object_fingerprint=rel.object_fingerprint,
    )


@router.get("/tables/{table_id}", response_model=TableDetail)
def get_table_detail(table_id: int) -> TableDetail:
    session = _session()
    try:
        table = session.scalar(
            select(CatalogTable)
            .where(CatalogTable.id == table_id)
            .options(
                selectinload(CatalogTable.columns),
                selectinload(CatalogTable.indexes).selectinload(CatalogIndex.columns),
            )
        )
        if table is None:
            raise HTTPException(status_code=404, detail="table not found")

        columns = [
            ColumnOut(
                id=c.id,
                column_name=c.column_name,
                ordinal_position=c.ordinal_position,
                data_type=c.data_type,
                character_maximum_length=c.character_maximum_length,
                numeric_precision=c.numeric_precision,
                numeric_scale=c.numeric_scale,
                nullable=c.is_nullable,
                default_value=c.default_value,
                comment=c.column_comment,
                primary_key=c.is_primary_key,
                unique=c.is_unique,
                object_fingerprint=c.object_fingerprint,
            )
            for c in sorted(table.columns, key=lambda x: x.ordinal_position)
            if c.active
        ]

        outbound_rels = session.scalars(
            select(CatalogRelation)
            .where(CatalogRelation.source_table_id == table.id, CatalogRelation.active.is_(True))
            .options(selectinload(CatalogRelation.columns))
        ).all()
        inbound_rels = session.scalars(
            select(CatalogRelation)
            .where(CatalogRelation.target_table_id == table.id, CatalogRelation.active.is_(True))
            .options(selectinload(CatalogRelation.columns))
        ).all()

        indexes = [
            IndexOut(
                id=ix.id,
                index_name=ix.index_name,
                is_unique=ix.is_unique,
                index_method=ix.index_method,
                index_definition=ix.index_definition,
                columns=[c.column_name for c in sorted(ix.columns, key=lambda x: x.ordinal_position)],
                object_fingerprint=ix.object_fingerprint,
            )
            for ix in table.indexes
            if ix.active
        ]

        return TableDetail(
            id=table.id,
            schema_name=table.schema_name,
            table_name=table.table_name,
            table_type=table.table_type,
            table_comment=table.table_comment,
            object_fingerprint=table.object_fingerprint,
            active=table.active,
            columns=columns,
            outbound_relations=[_relation_out(session, r) for r in outbound_rels],
            inbound_relations=[_relation_out(session, r) for r in inbound_rels],
            indexes=indexes,
        )
    finally:
        session.close()
