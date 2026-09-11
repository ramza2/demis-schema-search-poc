"""Health check service."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.db.session import check_connection, get_catalog_engine, get_medical_engine


def build_health_payload(settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    medical_ok = check_connection(get_medical_engine(cfg))
    catalog_ok = check_connection(get_catalog_engine(cfg))
    overall = "ok" if medical_ok and catalog_ok else "degraded"
    return {
        "status": overall,
        "backend": "ok",
        "medical_db": "ok" if medical_ok else "error",
        "catalog_db": "ok" if catalog_ok else "error",
        "step": cfg.current_step,
        "app_name": cfg.app_name,
    }
