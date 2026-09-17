"""Schema analysis run snapshot/diff APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas.schema_diff_api import (
    SchemaDiffResponse,
    SchemaRunListResponse,
    SnapshotCaptureResponse,
)
from app.services.schema_diff_service import SchemaDiffService

router = APIRouter(prefix="/api/v1/schema-diff", tags=["schema-diff"])


def _lookup_error(exc: LookupError) -> HTTPException:
    return HTTPException(status_code=404, detail=str(exc))


def _value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/targets/{target_id}/runs", response_model=SchemaRunListResponse)
def list_schema_runs(target_id: int) -> SchemaRunListResponse:
    service = SchemaDiffService()
    try:
        return service.list_runs(target_id)
    except LookupError as exc:
        raise _lookup_error(exc) from exc


@router.post(
    "/targets/{target_id}/baseline",
    response_model=SnapshotCaptureResponse,
)
def capture_latest_baseline(target_id: int) -> SnapshotCaptureResponse:
    """Capture current Catalog as baseline for the latest SUCCESS run only."""
    service = SchemaDiffService()
    try:
        return service.capture_latest_baseline(target_id)
    except LookupError as exc:
        raise _lookup_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/targets/{target_id}/compare", response_model=SchemaDiffResponse)
def compare_schema_runs(
    target_id: int,
    base_run_id: int = Query(gt=0),
    target_run_id: int = Query(gt=0),
) -> SchemaDiffResponse:
    service = SchemaDiffService()
    try:
        return service.compare(target_id, base_run_id, target_run_id)
    except LookupError as exc:
        raise _lookup_error(exc) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc
