"""DB analysis preflight API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.preflight_api import PreflightRequest, PreflightResponse
from app.services.preflight_service import PreflightService

router = APIRouter(prefix="/api/v1/preflight", tags=["preflight"])


@router.post("/targets/{target_id}", response_model=PreflightResponse)
def run_target_preflight(target_id: int, payload: PreflightRequest) -> PreflightResponse:
    """Validate connection and metadata-readiness without creating an analysis run."""
    service = PreflightService()
    try:
        return service.run(
            target_id=target_id,
            password=payload.password,
            schemas=payload.schemas,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
