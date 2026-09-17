"""Integration coverage for portable Catalog Package export."""

from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogAnalysisRun,
    CatalogColumn,
    CatalogIndex,
    CatalogIndexColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogSource,
    CatalogTable,
)
from app.models.catalog_category import CatalogCategory, CatalogTableCategory


ROOT = "demis_catalog_package"
EXPECTED_FILES = {
    "manifest.json",
    "database.json",
    "categories.json",
    "tables.json",
    "columns.json",
    "relations.json",
    "indexes.json",
    "erd.json",
}


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


def _create_fixture() -> int:
    suffix = uuid.uuid4().hex[:8]
    session = get_catalog_session_factory()()
    try:
        source = CatalogSource(
            source_name=f"package_source_{suffix}",
            db_type="oracle",
            host="SECRET_DB_HOST",
            port=1521,
            database_name="FREEPDB1",
            default_schema="DEMIS_OWNER",
            username="SECRET_DB_USER",
            encrypted_password="SECRET_CIPHERTEXT",
            connection_options={"secret_option": "DO_NOT_EXPORT"},
            enabled=True,
        )
        session.add(source)
        session.flush()

        run = CatalogAnalysisRun(
            source_id=source.id,
            status="SUCCESS",
            target_schema="DEMIS_OWNER",
            table_count=2,
            column_count=3,
            relation_count=1,
            index_count=1,
            schema_fingerprint=_fp("schema" + suffix),
        )
        session.add(run)
        session.flush()

        patient = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name="TB_PT_MST",
            table_type="BASE TABLE",
            table_comment="환자 기본정보",
            object_fingerprint=_fp("patient" + suffix),
            last_run_id=run.id,
            active=True,
        )
        encounter = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name="TB_ENC_HIST",
            table_type="BASE TABLE",
            table_comment="진료 이력",
            object_fingerprint=_fp("encounter" + suffix),
            last_run_id=run.id,
            active=True,
        )
        session.add_all([patient, encounter])
        session.flush()

        patient_id = CatalogColumn(
            table_id=patient.id,
            ordinal_position=1,
            column_name="PT_ID",
            data_type="NUMBER",
            is_nullable=False,
            column_comment="환자 식별자",
            is_primary_key=True,
            is_unique=True,
            object_fingerprint=_fp("pt_id" + suffix),
            last_run_id=run.id,
            active=True,
        )
        encounter_id = CatalogColumn(
            table_id=encounter.id,
            ordinal_position=1,
            column_name="ENC_ID",
            data_type="NUMBER",
            is_nullable=False,
            column_comment="진료 식별자",
            is_primary_key=True,
            is_unique=True,
            object_fingerprint=_fp("enc_id" + suffix),
            last_run_id=run.id,
            active=True,
        )
        encounter_patient_id = CatalogColumn(
            table_id=encounter.id,
            ordinal_position=2,
            column_name="PT_ID",
            data_type="NUMBER",
            is_nullable=False,
            column_comment="환자 식별자",
            is_primary_key=False,
            is_unique=False,
            object_fingerprint=_fp("enc_pt_id" + suffix),
            last_run_id=run.id,
            active=True,
        )
        session.add_all([patient_id, encounter_id, encounter_patient_id])
        session.flush()

        relation = CatalogRelation(
            source_id=source.id,
            constraint_name="FK_ENC_PATIENT",
            source_table_id=encounter.id,
            target_table_id=patient.id,
            relation_type="FOREIGN_KEY",
            object_fingerprint=_fp("relation" + suffix),
            last_run_id=run.id,
            active=True,
        )
        session.add(relation)
        session.flush()
        session.add(
            CatalogRelationColumn(
                relation_id=relation.id,
                ordinal_position=1,
                source_column_id=encounter_patient_id.id,
                target_column_id=patient_id.id,
            )
        )

        index = CatalogIndex(
            table_id=encounter.id,
            index_name="IX_ENC_PT_ID",
            is_unique=False,
            index_method="BTREE",
            index_definition=None,
            object_fingerprint=_fp("index" + suffix),
            last_run_id=run.id,
            active=True,
        )
        session.add(index)
        session.flush()
        session.add(
            CatalogIndexColumn(
                index_id=index.id,
                ordinal_position=1,
                column_name="PT_ID",
            )
        )

        category = CatalogCategory(
            source_id=source.id,
            category_key="patient",
            category_name="환자",
            description="환자 관련 테이블",
            sort_order=10,
            active=True,
        )
        session.add(category)
        session.flush()
        session.add(
            CatalogTableCategory(
                table_id=patient.id,
                category_id=category.id,
                is_primary=True,
                assignment_source="MANUAL",
                confidence=None,
                note="검토 완료",
            )
        )

        session.commit()
        return int(source.id)
    finally:
        session.close()


def _cleanup(source_id: int) -> None:
    session = get_catalog_session_factory()()
    try:
        session.execute(
            text(
                "DELETE FROM catalog_table_category WHERE table_id IN "
                "(SELECT id FROM catalog_table WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        )
        session.execute(text("DELETE FROM catalog_category WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_relation WHERE source_id = :sid"), {"sid": source_id})
        session.execute(
            text(
                "DELETE FROM catalog_index WHERE table_id IN "
                "(SELECT id FROM catalog_table WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        )
        session.execute(text("UPDATE catalog_table SET last_run_id = NULL WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_table WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_analysis_run WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_source WHERE id = :sid"), {"sid": source_id})
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def test_catalog_package_manifest_and_zip(client: TestClient) -> None:
    source_id = _create_fixture()
    try:
        manifest_response = client.get(f"/api/v1/catalog/package/{source_id}/manifest")
        assert manifest_response.status_code == 200, manifest_response.text
        manifest = manifest_response.json()
        assert manifest["package_format"] == "demis-catalog-package"
        assert manifest["package_version"] == "1.0"
        assert manifest["counts"]["tables"] == 2
        assert manifest["counts"]["relations"] == 1
        assert manifest["counts"]["categories"] == 1

        response = client.get(f"/api/v1/catalog/package/{source_id}/download")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/zip")
        assert "attachment; filename=" in response.headers["content-disposition"]

        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            assert names == {f"{ROOT}/{name}" for name in EXPECTED_FILES}

            documents = {
                name: json.loads(archive.read(f"{ROOT}/{name}"))
                for name in EXPECTED_FILES
            }

        database = documents["database.json"]
        assert database["source"]["source_name"].startswith("package_source_")
        assert database["security"]["credentials_exported"] is False
        assert "host" not in database["source"]
        assert "username" not in database["source"]

        serialized = json.dumps(documents, ensure_ascii=False)
        assert "SECRET_DB_HOST" not in serialized
        assert "SECRET_DB_USER" not in serialized
        assert "SECRET_CIPHERTEXT" not in serialized
        assert "DO_NOT_EXPORT" not in serialized

        tables = documents["tables.json"]["tables"]
        assert {item["table_key"] for item in tables} == {
            "DEMIS_OWNER.TB_PT_MST",
            "DEMIS_OWNER.TB_ENC_HIST",
        }
        patient = next(item for item in tables if item["table_name"] == "TB_PT_MST")
        assert patient["comment_provenance"] == "DB_COMMENT"
        assert patient["categories"] == ["patient"]

        assignments = documents["categories.json"]["table_assignments"]
        assert assignments == [
            {
                "assignment_source": "MANUAL",
                "category_key": "patient",
                "confidence": None,
                "is_primary": True,
                "note": "검토 완료",
                "table_key": "DEMIS_OWNER.TB_PT_MST",
            }
        ]

        relations = documents["relations.json"]["relations"]
        assert relations[0]["source_table_key"] == "DEMIS_OWNER.TB_ENC_HIST"
        assert relations[0]["target_table_key"] == "DEMIS_OWNER.TB_PT_MST"
        assert relations[0]["column_mapping"][0]["source_column"] == "PT_ID"

        manifest_in_zip = documents["manifest.json"]
        for item in manifest_in_zip["files"]:
            content = json.dumps(
                documents[item["path"]], ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8") + b"\n"
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
    finally:
        _cleanup(source_id)


def test_catalog_package_unknown_source_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/catalog/package/999999999/manifest")
    assert response.status_code == 404
    assert response.json()["detail"] == "catalog source not found"
