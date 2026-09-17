"""Persist and retrieve source-scoped validation artifacts."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.models.catalog_validation import CatalogPreflightResult
from app.schemas.preflight_api import PreflightResponse


def _json_payload(result: PreflightResponse) -> dict[str, Any]:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result.dict()  # pragma: no cover - pydantic v1 compatibility


def persist_preflight_result(result: PreflightResponse) -> None:
    """Store one append-only Preflight result after the API has completed."""
    ensure_catalog_schema()
    session = get_catalog_session_factory()()
    try:
        row = CatalogPreflightResult(
            source_id=result.target_id,
            status=result.status,
            schemas=list(result.schemas),
            result_json=_json_payload(result),
            generated_at=result.generated_at,
        )
        session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def latest_preflight_result(session, source_id: int) -> CatalogPreflightResult | None:
    """Return the newest persisted Preflight result for a Catalog Source."""
    return session.scalar(
        select(CatalogPreflightResult)
        .where(CatalogPreflightResult.source_id == source_id)
        .order_by(CatalogPreflightResult.generated_at.desc(), CatalogPreflightResult.id.desc())
        .limit(1)
    )
