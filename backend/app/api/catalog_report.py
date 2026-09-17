"""DB analysis report generation APIs."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Response

from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.services.catalog_report import build_db_analysis_report

router = APIRouter(prefix="/api/v1/catalog/report", tags=["catalog-report"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _build(source_id: int):
    session = _session()
    try:
        return build_db_analysis_report(session, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        session.close()


@router.get("/{source_id}/metadata")
def get_db_analysis_report_metadata(source_id: int) -> dict:
    """Generate the report and return safe report metadata."""
    return _build(source_id).metadata


@router.get("/{source_id}/download")
def download_db_analysis_report(source_id: int) -> Response:
    """Generate and download the DB analysis report as DOCX."""
    report = _build(source_id)
    ascii_fallback = "DEMIS_DB_analysis_report.docx"
    encoded = quote(report.filename)
    return Response(
        content=report.content,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded}"
            ),
            "X-Catalog-Report-Version": str(report.metadata["report_version"]),
        },
    )
