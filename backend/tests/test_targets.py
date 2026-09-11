"""Target management API tests."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))
    os.environ.setdefault(
        "MEDICAL_DB_PASSWORD", os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")
    )

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        yield test_client


def _medical_password() -> str:
    return os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")


def test_target_crud_and_no_password_in_payload(client: TestClient):
    name = f"target_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/v1/targets",
        json={
            "source_name": name,
            "db_type": "postgresql",
            "host": os.getenv("MEDICAL_DB_HOST", "localhost"),
            "port": int(os.getenv("MEDICAL_DB_PORT", "5433")),
            "database_name": os.getenv("MEDICAL_DB_NAME", "medical_demo"),
            "default_schema": "public",
            "username": os.getenv("MEDICAL_DB_USER", "medical_user"),
            "connection_options": None,
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert "password" not in body
    assert body["source_name"] == name
    target_id = body["id"]

    listed = client.get("/api/v1/targets")
    assert listed.status_code == 200
    assert any(t["id"] == target_id for t in listed.json())
    assert all("password" not in t for t in listed.json())

    updated = client.put(
        f"/api/v1/targets/{target_id}",
        json={"default_schema": "public", "enabled": True},
    )
    assert updated.status_code == 200, updated.text
    assert "password" not in updated.json()


def test_target_test_schemas_analyze_and_summary(client: TestClient):
    name = f"analyze_{uuid.uuid4().hex[:8]}"
    host = os.getenv("MEDICAL_DB_HOST", "localhost")
    # Inside docker compose network the backend uses medical-db:5432
    if host in {"localhost", "127.0.0.1"}:
        # Prefer compose service name when CATALOG points at catalog-db
        catalog_host = os.getenv("CATALOG_DB_HOST", "localhost")
        if catalog_host == "catalog-db":
            host = "medical-db"
            port = 5432
        else:
            port = int(os.getenv("MEDICAL_DB_PORT", "5433"))
    else:
        port = int(os.getenv("MEDICAL_DB_PORT", "5432"))

    create = client.post(
        "/api/v1/targets",
        json={
            "source_name": name,
            "db_type": "postgresql",
            "host": host,
            "port": port,
            "database_name": os.getenv("MEDICAL_DB_NAME", "medical_demo"),
            "default_schema": "public",
            "username": os.getenv("MEDICAL_DB_USER", "medical_user"),
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    password = _medical_password()

    probed = client.post(f"/api/v1/targets/{target_id}/test", json={"password": password})
    assert probed.status_code == 200, probed.text
    assert probed.json()["connected"] is True
    assert "PostgreSQL" in probed.json()["dbms_product"]

    schemas = client.post(f"/api/v1/targets/{target_id}/schemas", json={"password": password})
    assert schemas.status_code == 200, schemas.text
    assert "public" in schemas.json()["schemas"]

    analyzed = client.post(
        f"/api/v1/targets/{target_id}/analyze",
        json={"password": password, "schemas": ["public"]},
    )
    assert analyzed.status_code == 200, analyzed.text
    payload = analyzed.json()
    assert payload["status"] == "SUCCESS"
    assert payload["tables"] > 0
    assert "password" not in str(payload).lower() or password not in str(payload)

    tables = client.get(f"/api/v1/schema/tables?source_id={target_id}")
    assert tables.status_code == 200
    assert len(tables.json()) == payload["tables"]

    summary = client.get(f"/api/v1/targets/{target_id}/catalog-summary")
    assert summary.status_code == 200, summary.text
    summary_body = summary.json()
    assert summary_body["tables"] == payload["tables"]
    assert summary_body["last_success_fingerprint"]


def test_medical_demo_analyze_still_works(client: TestClient):
    response = client.post("/api/v1/schema/analyze")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["source"] == "medical_demo"


def test_password_not_persisted_on_source(client: TestClient):
    from sqlalchemy import create_engine, text

    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    engine = create_engine(
        f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}",
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'catalog_source'
                    """
                )
            )
        }
    assert "password" not in cols
    assert "username" in cols
