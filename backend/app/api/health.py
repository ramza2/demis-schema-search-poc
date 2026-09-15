"""Health API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.services.health import build_health_payload

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return build_health_payload()
