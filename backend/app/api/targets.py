"""Target management APIs (credentials encrypted at rest; never returned)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from app.models.catalog import CatalogSource
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
from app.services.schema_diff_service import SchemaDiffService
from app.services.target_service import TargetConnectionTimeoutError, TargetService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/targets", tags=["targets"])


def _http_from_lookup(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _http_from_value(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _http_from_runtime(exc: RuntimeError) -> HTTPException:
    if isinstance(exc, TargetConnectionTimeoutError):
        return HTTPException(status_code=504, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _to_target_out(source: CatalogSource) -> TargetOut:
    """Map ORM row to API model without exposing ciphertext."""
    return TargetOut(
        id=source.id,
        source_name=source.source_name,
        db_type=source.db_type,
        host=source.host,
        port=source.port,
        database_name=source.database_name,
        default_schema=source.default_schema,
        username=source.username,
        connection_options=source.connection_options,
        enabled=source.enabled,
        has_saved_password=bool(source.encrypted_password),
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


@router.get("", response_model=list[TargetOut])
def list_targets() -> list[TargetOut]:
    service = TargetService()
    return [_to_target_out(t) for t in service.list_targets()]


@router.post("", response_model=TargetOut, status_code=201)
def create_target(payload: TargetCreate) -> TargetOut:
    service = TargetService()
    try:
        source = service.create_target(payload)
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    return _to_target_out(source)


@router.put("/{target_id}", response_model=TargetOut)
def update_target(target_id: int, payload: TargetUpdate) -> TargetOut:
    service = TargetService()
    try:
        source = service.update_target(target_id, payload)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    return _to_target_out(source)


@router.delete("/{target_id}", status_code=204)
def delete_target(target_id: int) -> Response:
    service = TargetService()
    try:
        service.delete_target(target_id)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    return Response(status_code=204)


@router.post("/{target_id}/test", response_model=TestConnectionResponse)
def test_target_connection(
    target_id: int, body: PasswordRequest | None = None
) -> TestConnectionResponse:
    service = TargetService()
    password = body.password if body is not None else None
    try:
        result = service.test_connection(target_id, password)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except ValueError as exc:
        raise _http_from_value(exc) from exc
    except RuntimeError as exc:
        raise _http_from_runtime(exc) from exc
    return TestConnectionResponse(**result)


@router.post("/{target_id}/schemas", response_model=SchemaListResponse)
def list_target_schemas(
    target_id: int, body: PasswordRequest | None = None
) -> SchemaListResponse:
    service = TargetService()
    password = body.password if body is not None else None
    try:
        schemas = service.list_schemas(target_id, password)
    except LookupError as exc:
        raise _http_from_lookup(exc) from exc
    except ValueError as exc:
        raise _http_from_value(exc) from exc
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
    except RuntimeError as exc:
        # Connect/probe timeout -> 504; other connection failures -> 502.
        # Post-connect inspect/catalog errors still return FAILED AnalyzeResponse.
        raise _http_from_runtime(exc) from exc

    # Snapshot persistence is intentionally secondary to schema analysis. A successful
    # analysis must remain SUCCESS even if history capture encounters an operational
    # issue; the failure is logged and the Run Diff UI will show snapshot unavailable.
    if run.status == "SUCCESS":
        try:
            SchemaDiffService().capture_run(
                int(run.id),
                expected_source_id=target_id,
                capture_mode="ANALYSIS_API",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Schema analysis succeeded but run snapshot capture failed: run_id=%s error=%s",
                run.id,
                exc,
            )

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
