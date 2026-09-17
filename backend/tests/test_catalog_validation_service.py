"""Focused persistence test for DB Analysis Preflight history."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.session import get_catalog_session_factory
from app.models.catalog import CatalogSource
from app.schemas.preflight_api import (
    PreflightCheck,
    PreflightConnection,
    PreflightResponse,
    PreflightSecurity,
    PreflightSummary,
)
from app.services.catalog_validation_service import latest_preflight_result, persist_preflight_result


def _catalog_env() -> None:
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))


def test_persist_preflight_result_keeps_latest_history() -> None:
    _catalog_env()
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.db.catalog_bootstrap import ensure_catalog_schema

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    ensure_catalog_schema()

    session = get_catalog_session_factory()()
    suffix = uuid.uuid4().hex[:8]
    try:
        source = CatalogSource(
            source_name=f"preflight_history_{suffix}",
            db_type="oracle",
            host="oracle-mock",
            port=1521,
            database_name="FREEPDB1",
            default_schema="DEMIS_OWNER",
            username="DEMIS_RO",
            enabled=True,
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        source_id = int(source.id)
    finally:
        session.close()

    try:
        result = PreflightResponse(
            target_id=source_id,
            source_name=f"preflight_history_{suffix}",
            db_type="oracle",
            schemas=["DEMIS_OWNER"],
            status="READY",
            generated_at=datetime.now(timezone.utc),
            connection=PreflightConnection(
                dbms_product="Oracle",
                db_version="Oracle Test",
                database_or_service="FREEPDB1",
                current_user="DEMIS_RO",
            ),
            summary=PreflightSummary(
                passed=10,
                warnings=0,
                blocked=0,
                tables=25,
                columns=206,
                primary_keys=26,
                unique_constraints=9,
                foreign_keys=40,
                indexes=19,
                table_comments=25,
                column_comments=13,
            ),
            checks=[
                PreflightCheck(
                    key="CONNECTION",
                    name="DB Connection",
                    status="PASS",
                    detail="Target DB connection succeeded.",
                )
            ],
            security=PreflightSecurity(),
        )
        persist_preflight_result(result)

        verify = get_catalog_session_factory()()
        try:
            row = latest_preflight_result(verify, source_id)
            assert row is not None
            assert row.status == "READY"
            assert row.schemas == ["DEMIS_OWNER"]
            assert row.result_json["summary"]["tables"] == 25
            assert row.result_json["connection"]["current_user"] == "DEMIS_RO"
        finally:
            verify.close()
    finally:
        cleanup = get_catalog_session_factory()()
        try:
            cleanup.execute(text("DELETE FROM catalog_preflight_result WHERE source_id = :sid"), {"sid": source_id})
            cleanup.execute(text("DELETE FROM catalog_source WHERE id = :sid"), {"sid": source_id})
            cleanup.commit()
        finally:
            cleanup.close()
