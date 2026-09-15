"""Health check service."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.db.session import check_connection, get_catalog_engine, get_medical_engine


def build_health_payload(settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    catalog_ok = check_connection(get_catalog_engine(cfg))
    medical_required = bool(cfg.medical_db_required)

    if medical_required:
        medical_ok = check_connection(get_medical_engine(cfg))
        medical_status = "ok" if medical_ok else "error"
        overall = "ok" if catalog_ok and medical_ok else "degraded"
    else:
        # Production without demo profile: do not create/probe medical_demo at all.
        medical_status = "disabled"
        overall = "ok" if catalog_ok else "degraded"

    return {
        "status": overall,
        "backend": "ok",
        "medical_db": medical_status,
        "catalog_db": "ok" if catalog_ok else "error",
        "medical_db_required": medical_required,
        "step": cfg.current_step,
        "app_name": cfg.app_name,
    }
