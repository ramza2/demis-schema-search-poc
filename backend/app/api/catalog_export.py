"""Catalog Package export APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.services.catalog_package_finalizer import build_final_catalog_package

router = APIRouter(prefix="/api/v1/catalog/package", tags=["catalog-package"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _build(source_id: int):
    session = _session()
    try:
        return build_final_catalog_package(session, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/{source_id}/manifest")
def get_catalog_package_manifest(source_id: int) -> dict:
    """Preview finalized Catalog Package manifest without returning ZIP bytes."""
    return _build(source_id).manifest


@router.get("/{source_id}/download")
def download_catalog_package(source_id: int) -> Response:
    """Download the finalized portable Catalog Package ZIP for one Catalog Source."""
    package = _build(source_id)
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "X-Catalog-Package-Version": str(package.manifest["package_version"]),
            "X-Catalog-Package-Readiness": str(package.manifest["package_readiness"]),
        },
    )
