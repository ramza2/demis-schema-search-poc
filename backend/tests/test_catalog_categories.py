"""Integration coverage for source-scoped Catalog Category APIs."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_catalog_session_factory
from app.models.catalog import CatalogSource, CatalogTable


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


def _create_source_and_table() -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:8]
    session = get_catalog_session_factory()()
    try:
        source = CatalogSource(
            source_name=f"category_source_{suffix}",
            db_type="oracle",
            host="localhost",
            port=1521,
            database_name="FREEPDB1",
            default_schema="DEMIS_OWNER",
            username="DEMIS_RO",
            enabled=True,
        )
        session.add(source)
        session.flush()
        table = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name=f"TB_CATEGORY_{suffix.upper()}",
            table_type="BASE TABLE",
            table_comment="category api fixture",
            object_fingerprint=(suffix * 8)[:64],
            active=True,
        )
        session.add(table)
        session.commit()
        session.refresh(source)
        session.refresh(table)
        return int(source.id), int(table.id)
    finally:
        session.close()


def _delete_source(source_id: int) -> None:
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
        session.execute(text("DELETE FROM catalog_table WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_source WHERE id = :sid"), {"sid": source_id})
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def test_category_crud_and_table_assignment(client: TestClient) -> None:
    source_id, table_id = _create_source_and_table()
    try:
        patient = client.post(
            "/api/v1/catalog/categories",
            json={
                "source_id": source_id,
                "category_key": "patient",
                "category_name": "환자",
                "description": "환자 기본정보",
                "sort_order": 10,
            },
        )
        assert patient.status_code == 201, patient.text
        patient_id = patient.json()["id"]

        lab = client.post(
            "/api/v1/catalog/categories",
            json={
                "source_id": source_id,
                "category_key": "laboratory",
                "category_name": "임상검사",
                "sort_order": 20,
            },
        )
        assert lab.status_code == 201, lab.text
        lab_id = lab.json()["id"]

        duplicate = client.post(
            "/api/v1/catalog/categories",
            json={
                "source_id": source_id,
                "category_key": "patient",
                "category_name": "중복",
            },
        )
        assert duplicate.status_code == 409

        assigned = client.put(
            f"/api/v1/catalog/tables/{table_id}/categories",
            json={
                "assignments": [
                    {
                        "category_id": patient_id,
                        "is_primary": True,
                        "assignment_source": "MANUAL",
                    },
                    {
                        "category_id": lab_id,
                        "is_primary": False,
                        "assignment_source": "AUTO",
                        "confidence": 0.82,
                    },
                ]
            },
        )
        assert assigned.status_code == 200, assigned.text
        body = assigned.json()
        assert [item["category_key"] for item in body] == ["patient", "laboratory"]
        assert body[0]["is_primary"] is True
        assert body[1]["confidence"] == pytest.approx(0.82)

        table_categories = client.get(f"/api/v1/catalog/tables/{table_id}/categories")
        assert table_categories.status_code == 200
        assert len(table_categories.json()) == 2

        patient_tables = client.get(f"/api/v1/catalog/categories/{patient_id}/tables")
        assert patient_tables.status_code == 200
        assert patient_tables.json()[0]["table_id"] == table_id
        assert patient_tables.json()[0]["is_primary"] is True

        categories = client.get("/api/v1/catalog/categories", params={"source_id": source_id})
        assert categories.status_code == 200
        assert {item["category_key"] for item in categories.json()} == {"patient", "laboratory"}
        patient_out = next(item for item in categories.json() if item["category_key"] == "patient")
        assert patient_out["table_count"] == 1

        updated = client.put(
            f"/api/v1/catalog/categories/{lab_id}",
            json={"category_name": "검사", "description": "검사 업무"},
        )
        assert updated.status_code == 200
        assert updated.json()["category_name"] == "검사"

        deleted = client.delete(f"/api/v1/catalog/categories/{lab_id}")
        assert deleted.status_code == 204
        remaining = client.get(f"/api/v1/catalog/tables/{table_id}/categories")
        assert [item["category_key"] for item in remaining.json()] == ["patient"]
    finally:
        _delete_source(source_id)


def test_table_assignment_rejects_category_from_other_source(client: TestClient) -> None:
    source_a, table_a = _create_source_and_table()
    source_b, _table_b = _create_source_and_table()
    try:
        category = client.post(
            "/api/v1/catalog/categories",
            json={
                "source_id": source_b,
                "category_key": "foreign-category",
                "category_name": "다른 Source",
            },
        )
        assert category.status_code == 201
        category_id = category.json()["id"]

        response = client.put(
            f"/api/v1/catalog/tables/{table_a}/categories",
            json={
                "assignments": [
                    {
                        "category_id": category_id,
                        "is_primary": True,
                        "assignment_source": "MANUAL",
                    }
                ]
            },
        )
        assert response.status_code == 400
        assert "different source" in response.json()["detail"]
    finally:
        _delete_source(source_a)
        _delete_source(source_b)
