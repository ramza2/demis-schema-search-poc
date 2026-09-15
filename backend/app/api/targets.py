"""Target management APIs (password never persisted)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.schema_api import AnalyzeResponse
from app.schemas.target_api import (
    AnalyzeRequest,
    CatalogSummaryResponse,
    PasswordRequest,
    SchemaListResponse,
    TargetCreate,
    TargetOut,
    TargetUpdate,
    TestConnectionResponse,
)
from app.services.target_service import TargetService

router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _http_from_lookup(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _http_from_value(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _http_from_runtime(exc: RuntimeError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@router.get("", response_model=list[TargetOut])
def list_targets() -> list[TargetOut]:
    service = TargetService()
    return [TargetOut.model_validate(t) for t in service.list_targets()]


@router.post("", response_model=TargetOut, status_code=201)
def create_target(payload: TargetCreate) -> TargetOut:
    service = TargetService()
    try:
        source = service.create_target(payload)
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    return TargetOut.model_validate(source)


@router.put("/{target_id}", response_model=TargetOut)
def update_target(target_id: int, payload: TargetUpdate) -> TargetOut:
    service = TargetService()
    try:
        source = service.update_target(target_id, payload)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    return TargetOut.model_validate(source)


@router.post("/{target_id}/test", response_model=TestConnectionResponse)
def test_target_connection(target_id: int, body: PasswordRequest) -> TestConnectionResponse:
    service = TargetService()
    try:
        result = service.test_connection(target_id, body.password)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except RuntimeError as exc:
        raise _http_from_runtime(exc) from exc
    return TestConnectionResponse(**result)


@router.post("/{target_id}/schemas", response_model=SchemaListResponse)
def list_target_schemas(target_id: int, body: PasswordRequest) -> SchemaListResponse:
    service = TargetService()
    try:
        schemas = service.list_schemas(target_id, body.password)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except RuntimeError as exc:
        raise _http_from_runtime(exc) from exc
    return SchemaListResponse(schemas=schemas)


@router.post("/{target_id}/analyze", response_model=AnalyzeResponse)
def analyze_target(target_id: int, body: AnalyzeRequest) -> AnalyzeResponse:
    service = TargetService()
    try:
        source = service.get_target(target_id)
        run = service.analyze_target(target_id, body.password, body.schemas)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    return AnalyzeResponse(
        run_id=run.id,
        status=run.status,
        source=source.source_name,
        schema_name=run.target_schema,
        tables=run.table_count or 0,
        columns=run.column_count or 0,
        relations=run.relation_count or 0,
        indexes=run.index_count or 0,
        schema_fingerprint=run.schema_fingerprint,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
    )


@router.get("/{target_id}/catalog-summary", response_model=CatalogSummaryResponse)
def get_catalog_summary(target_id: int) -> CatalogSummaryResponse:
    service = TargetService()
    try:
        summary = service.catalog_summary(target_id)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    return CatalogSummaryResponse(**summary)
