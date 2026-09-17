"""Catalog Package export APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.services.catalog_package import build_catalog_package
from app.services.catalog_package_finalizer import build_final_catalog_package

router = APIRouter(prefix="/api/v1/catalog/package", tags=["catalog-package"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _build(source_id: int, *, finalized: bool = False):
    session = _session()
    try:
        builder = build_final_catalog_package if finalized else build_catalog_package
        return builder(session, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/{source_id}/manifest")
def get_catalog_package_manifest(source_id: int) -> dict:
    """Preview legacy v1 manifest for backward-compatible consumers."""
    return _build(source_id).manifest


@router.get("/{source_id}/download")
def download_catalog_package(source_id: int) -> Response:
    """Download the backward-compatible v1 Catalog Package."""
    package = _build(source_id)
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "X-Catalog-Package-Version": str(package.manifest["package_version"]),
        },
    )


@router.get("/{source_id}/final/manifest")
def get_final_catalog_package_manifest(source_id: int) -> dict:
    """Preview finalized v2 handoff package manifest."""
    return _build(source_id, finalized=True).manifest


@router.get("/{source_id}/final/download")
def download_final_catalog_package(source_id: int) -> Response:
    """Download finalized v2 handoff ZIP with report, validation, snapshot and diff."""
    package = _build(source_id, finalized=True)
    return Response(
        content=package.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{package.filename}"',
            "X-Catalog-Package-Version": str(package.manifest["package_version"]),
            "X-Catalog-Package-Readiness": str(package.manifest["package_readiness"]),
        },
    )
