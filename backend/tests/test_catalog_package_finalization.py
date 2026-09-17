"""Integration coverage for finalized Catalog Package v2."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_catalog_session_factory
from app.models.catalog import CatalogAnalysisRun, CatalogColumn, CatalogSource, CatalogTable
from app.models.catalog_history import CatalogAnalysisSnapshot
from app.models.catalog_validation import CatalogPreflightResult


ROOT = "demis_catalog_package"


def _catalog_env() -> None:
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))


@pytest.fixture()
def client():
    _catalog_env()
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.db.catalog_bootstrap import ensure_catalog_schema
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    ensure_catalog_schema()
    with TestClient(create_app()) as test_client:
        yield test_client


def _fp(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _snapshot_payload() -> dict:
    return {
        "snapshot_version": "1.0",
        "source": {"source_name": "fixture", "db_type": "oracle", "database_name": "FREEPDB1"},
        "schemas": ["DEMIS_OWNER"],
        "tables": [
            {
                "schema": "DEMIS_OWNER",
                "name": "TB_PT_MST",
                "table_type": "BASE TABLE",
                "comment": "환자 기본정보",
            }
        ],
        "columns": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_PT_MST",
                "ordinal_position": 1,
                "name": "PT_ID",
                "data_type": "NUMBER",
                "character_maximum_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
                "nullable": False,
                "default": None,
                "comment": "환자 식별자",
            }
        ],
        "key_constraints": [],
        "foreign_keys": [],
        "indexes": [],
    }


def _create_fixture() -> int:
    suffix = uuid.uuid4().hex[:8]
    session = get_catalog_session_factory()()
    try:
        source = CatalogSource(
            source_name=f"final_package_{suffix}",
            db_type="oracle",
            host="SECRET_DB_HOST",
            port=1521,
            database_name="FREEPDB1",
            default_schema="DEMIS_OWNER",
            username="SECRET_DB_USER",
            encrypted_password="SECRET_CIPHERTEXT",
            connection_options={"service_name": "FREEPDB1", "secret": "DO_NOT_EXPORT"},
            enabled=True,
        )
        session.add(source)
        session.flush()

        runs = []
        for idx in (1, 2):
            run = CatalogAnalysisRun(
                source_id=source.id,
                status="SUCCESS",
                target_schema="DEMIS_OWNER",
                table_count=1,
                column_count=1,
                relation_count=0,
                index_count=0,
                schema_fingerprint=_fp(f"schema-{suffix}"),
                finished_at=datetime.now(timezone.utc),
            )
            session.add(run)
            session.flush()
            runs.append(run)
            session.add(
                CatalogAnalysisSnapshot(
                    source_id=source.id,
                    run_id=run.id,
                    snapshot_version="1.0",
                    capture_mode="ANALYSIS_API",
                    payload=_snapshot_payload(),
                )
            )

        table = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name="TB_PT_MST",
            table_type="BASE TABLE",
            table_comment="환자 기본정보",
            object_fingerprint=_fp("table-" + suffix),
            last_run_id=runs[-1].id,
            active=True,
        )
        session.add(table)
        session.flush()
        session.add(
            CatalogColumn(
                table_id=table.id,
                ordinal_position=1,
                column_name="PT_ID",
                data_type="NUMBER",
                is_nullable=False,
                column_comment="환자 식별자",
                is_primary_key=True,
                is_unique=True,
                object_fingerprint=_fp("column-" + suffix),
                last_run_id=runs[-1].id,
                active=True,
            )
        )

        preflight_json = {
            "target_id": int(source.id),
            "source_name": source.source_name,
            "db_type": "oracle",
            "schemas": ["DEMIS_OWNER"],
            "status": "READY",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "connection": {
                "dbms_product": "Oracle",
                "db_version": "Oracle Test",
                "database_or_service": "FREEPDB1",
                "current_user": "SECRET_DB_USER",
            },
            "summary": {
                "passed": 10,
                "warnings": 0,
                "blocked": 0,
                "tables": 1,
                "columns": 1,
                "primary_keys": 1,
                "unique_constraints": 0,
                "foreign_keys": 0,
                "indexes": 0,
                "table_comments": 1,
                "column_comments": 1,
            },
            "checks": [
                {
                    "key": "CONNECTION",
                    "name": "DB Connection",
                    "status": "PASS",
                    "schema_name": None,
                    "count": None,
                    "detail": "SECRET_DB_USER connected to SECRET_DB_HOST",
                }
            ],
            "security": {
                "metadata_select_only": True,
                "business_data_selected": False,
                "credentials_returned": False,
            },
        }
        session.add(
            CatalogPreflightResult(
                source_id=source.id,
                status="READY",
                schemas=["DEMIS_OWNER"],
                result_json=preflight_json,
                generated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
        return int(source.id)
    finally:
        session.close()


def _cleanup(source_id: int) -> None:
    session = get_catalog_session_factory()()
    try:
        session.execute(text("DELETE FROM catalog_preflight_result WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_analysis_snapshot WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("UPDATE catalog_column SET last_run_id = NULL WHERE table_id IN (SELECT id FROM catalog_table WHERE source_id = :sid)"), {"sid": source_id})
        session.execute(text("UPDATE catalog_table SET last_run_id = NULL WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_table WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_analysis_run WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_source WHERE id = :sid"), {"sid": source_id})
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_final_catalog_package_contains_handoff_artifacts(client: TestClient) -> None:
    source_id = _create_fixture()
    try:
        response = client.get(f"/api/v1/catalog/package/{source_id}/final/manifest")
        assert response.status_code == 200, response.text
        manifest = response.json()
        assert manifest["package_version"] == "2.0"
        assert manifest["package_readiness"] == "READY"
        assert manifest["artifacts"]["schema_snapshot"]["available"] is True
        assert manifest["artifacts"]["preflight"]["status"] == "READY"
        assert manifest["artifacts"]["latest_diff"]["available"] is True
        assert manifest["artifacts"]["latest_diff"]["identical"] is True
        assert manifest["artifacts"]["db_analysis_report"]["available"] is True

        package_response = client.get(f"/api/v1/catalog/package/{source_id}/final/download")
        assert package_response.status_code == 200, package_response.text
        assert package_response.headers["x-catalog-package-version"] == "2.0"
        assert package_response.headers["x-catalog-package-readiness"] == "READY"

        with zipfile.ZipFile(io.BytesIO(package_response.content)) as archive:
            names = set(archive.namelist())
            required = {
                f"{ROOT}/manifest.json",
                f"{ROOT}/database.json",
                f"{ROOT}/tables.json",
                f"{ROOT}/columns.json",
                f"{ROOT}/relations.json",
                f"{ROOT}/indexes.json",
                f"{ROOT}/categories.json",
                f"{ROOT}/erd.json",
                f"{ROOT}/analysis/latest_run.json",
                f"{ROOT}/analysis/schema_snapshot.json",
                f"{ROOT}/validation/preflight.json",
                f"{ROOT}/diff/latest.json",
                f"{ROOT}/diff/latest_summary.md",
                f"{ROOT}/PACKAGE_README.md",
            }
            assert required.issubset(names)
            assert any(name.startswith(f"{ROOT}/reports/") and name.endswith(".docx") for name in names)

            preflight = json.loads(archive.read(f"{ROOT}/validation/preflight.json"))
            assert preflight["connection"]["current_user_exported"] is False
            text_payload = "\n".join(
                archive.read(name).decode("utf-8")
                for name in names
                if name.endswith((".json", ".md"))
            )
            assert "SECRET_DB_HOST" not in text_payload
            assert "SECRET_DB_USER" not in text_payload
            assert "SECRET_CIPHERTEXT" not in text_payload
            assert "DO_NOT_EXPORT" not in text_payload

            manifest_in_zip = json.loads(archive.read(f"{ROOT}/manifest.json"))
            for item in manifest_in_zip["files"]:
                content = archive.read(f"{ROOT}/{item['path']}")
                assert hashlib.sha256(content).hexdigest() == item["sha256"]
    finally:
        _cleanup(source_id)


def test_final_catalog_package_unknown_source_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/package/999999999/final/manifest")
    assert response.status_code == 404
    assert response.json()["detail"] == "catalog source not found"
