"""Target management API tests (encrypted credentials, edit, delete)."""

from __future__ import annotations

import os
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def _ensure_encryption_key() -> str:
    key = os.environ.get("TARGET_CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["TARGET_CREDENTIAL_ENCRYPTION_KEY"] = key
    return key


def _delete_target(source_id: int) -> None:
    """Remove a target and dependent catalog rows (test cleanup)."""
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.begin() as conn:
        table_ids = [
            r[0]
            for r in conn.execute(
                text("SELECT id FROM catalog_table WHERE source_id = :sid"),
                {"sid": source_id},
            )
        ]
        conn.execute(
            text("UPDATE catalog_table SET last_run_id = NULL WHERE source_id = :sid"),
            {"sid": source_id},
        )
        if table_ids:
            conn.execute(
                text(
                    "UPDATE catalog_column SET last_run_id = NULL WHERE table_id = ANY(:ids)"
                ),
                {"ids": table_ids},
            )
            conn.execute(
                text(
                    "UPDATE catalog_index SET last_run_id = NULL WHERE table_id = ANY(:ids)"
                ),
                {"ids": table_ids},
            )
            conn.execute(
                text(
                    """
                    UPDATE catalog_key_constraint SET last_run_id = NULL
                    WHERE table_id = ANY(:ids)
                    """
                ),
                {"ids": table_ids},
            )
        conn.execute(
            text("UPDATE catalog_relation SET last_run_id = NULL WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_relation WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_table WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_search_document WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_embedding_run WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_analysis_run WHERE source_id = :sid"),
            {"sid": source_id},
        )
        conn.execute(
            text("DELETE FROM catalog_source WHERE id = :sid"),
            {"sid": source_id},
        )


@pytest.fixture()
def client():
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))
    os.environ.setdefault(
        "MEDICAL_DB_PASSWORD", os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")
    )
    _ensure_encryption_key()

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


def _medical_host_port() -> tuple[str, int]:
    host = os.getenv("MEDICAL_DB_HOST", "localhost")
    if host in {"localhost", "127.0.0.1"}:
        catalog_host = os.getenv("CATALOG_DB_HOST", "localhost")
        if catalog_host == "catalog-db":
            return "medical-db", 5432
        return host, int(os.getenv("MEDICAL_DB_PORT", "5433"))
    return host, int(os.getenv("MEDICAL_DB_PORT", "5432"))


def _target_payload(name: str, *, password: str | None = None) -> dict:
    host, port = _medical_host_port()
    body = {
        "source_name": name,
        "db_type": "postgresql",
        "host": host,
        "port": port,
        "database_name": os.getenv("MEDICAL_DB_NAME", "medical_demo"),
        "default_schema": "public",
        "username": os.getenv("MEDICAL_DB_USER", "medical_user"),
        "password": password if password is not None else _medical_password(),
        "connection_options": None,
        "enabled": True,
    }
    return body


def _assert_no_secret_leak(payload: object, *secrets: str) -> None:
    blob = str(payload)
    assert "encrypted_password" not in blob
    for secret in secrets:
        if secret:
            assert secret not in blob


def test_target_crud_encrypted_password_not_in_api(client: TestClient):
    name = f"target_{uuid.uuid4().hex[:8]}"
    password = _medical_password()
    create = client.post("/api/v1/targets", json=_target_payload(name, password=password))
    assert create.status_code == 201, create.text
    body = create.json()
    assert "password" not in body
    assert "encrypted_password" not in body
    assert body["has_saved_password"] is True
    assert body["source_name"] == name
    target_id = body["id"]
    try:
        listed = client.get("/api/v1/targets")
        assert listed.status_code == 200
        row = next(t for t in listed.json() if t["id"] == target_id)
        assert row["has_saved_password"] is True
        assert all("password" not in t for t in listed.json())
        assert all("encrypted_password" not in t for t in listed.json())
        _assert_no_secret_leak(listed.json(), password)

        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"default_schema": "public", "enabled": True},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True
        assert "password" not in updated.json()
        assert "encrypted_password" not in updated.json()
    finally:
        _delete_target(target_id)


def test_password_stored_encrypted_not_plaintext(client: TestClient):
    name = f"enc_{uuid.uuid4().hex[:8]}"
    password = f"plain-secret-{uuid.uuid4().hex[:8]}"
    create = client.post("/api/v1/targets", json=_target_payload(name, password=password))
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    try:
        engine = create_engine(_catalog_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT encrypted_password FROM catalog_source WHERE id = :sid"
                ),
                {"sid": target_id},
            ).one()
        ciphertext = row[0]
        assert ciphertext
        assert password not in ciphertext
        assert ciphertext != password
    finally:
        _delete_target(target_id)


def test_update_keeps_password_when_omitted(client: TestClient):
    name = f"keep_{uuid.uuid4().hex[:8]}"
    password = f"keep-secret-{uuid.uuid4().hex[:8]}"
    create = client.post("/api/v1/targets", json=_target_payload(name, password=password))
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT encrypted_password FROM catalog_source WHERE id = :sid"),
            {"sid": target_id},
        ).scalar_one()
    try:
        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"username": os.getenv("MEDICAL_DB_USER", "medical_user")},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True
        with engine.connect() as conn:
            after = conn.execute(
                text("SELECT encrypted_password FROM catalog_source WHERE id = :sid"),
                {"sid": target_id},
            ).scalar_one()
        assert after == before
    finally:
        _delete_target(target_id)


def test_update_replaces_password(client: TestClient):
    name = f"repl_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/v1/targets",
        json=_target_payload(name, password="old-password-value"),
    )
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        before = conn.execute(
            text("SELECT encrypted_password FROM catalog_source WHERE id = :sid"),
            {"sid": target_id},
        ).scalar_one()
    try:
        new_password = "new-password-value"
        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"password": new_password},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True
        with engine.connect() as conn:
            after = conn.execute(
                text("SELECT encrypted_password FROM catalog_source WHERE id = :sid"),
                {"sid": target_id},
            ).scalar_one()
        assert after != before
        assert new_password not in after
        assert "old-password-value" not in after
    finally:
        _delete_target(target_id)


def test_legacy_target_without_password_compatible(client: TestClient):
    """Existing rows with NULL encrypted_password report has_saved_password=false."""
    name = f"legacy_{uuid.uuid4().hex[:8]}"
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    # Ensure column exists via API bootstrap first
    client.get("/api/v1/targets")
    with engine.begin() as conn:
        source_id = conn.execute(
            text(
                """
                INSERT INTO catalog_source (
                    source_name, db_type, host, port, database_name,
                    default_schema, username, encrypted_password, enabled
                ) VALUES (
                    :name, 'postgresql', 'localhost', 5432, 'demo',
                    'public', 'u', NULL, TRUE
                ) RETURNING id
                """
            ),
            {"name": name},
        ).scalar_one()
    try:
        listed = client.get("/api/v1/targets")
        assert listed.status_code == 200
        row = next(t for t in listed.json() if t["id"] == source_id)
        assert row["has_saved_password"] is False
        assert "password" not in row
        assert "encrypted_password" not in row

        # Operations without password -> 400
        probed = client.post(f"/api/v1/targets/{source_id}/test", json={})
        assert probed.status_code == 400, probed.text

        # Edit can attach a credential
        password = _medical_password()
        updated = client.put(
            f"/api/v1/targets/{source_id}",
            json={
                "host": _medical_host_port()[0],
                "port": _medical_host_port()[1],
                "database_name": os.getenv("MEDICAL_DB_NAME", "medical_demo"),
                "username": os.getenv("MEDICAL_DB_USER", "medical_user"),
                "password": password,
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True
    finally:
        _delete_target(source_id)


def test_saved_password_used_for_test_schemas_analyze(client: TestClient):
    name = f"saved_{uuid.uuid4().hex[:8]}"
    password = _medical_password()
    create = client.post("/api/v1/targets", json=_target_payload(name, password=password))
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    try:
        # No password in request — use saved credential
        probed = client.post(f"/api/v1/targets/{target_id}/test", json={})
        assert probed.status_code == 200, probed.text
        assert probed.json()["connected"] is True

        schemas = client.post(f"/api/v1/targets/{target_id}/schemas", json={})
        assert schemas.status_code == 200, schemas.text
        assert "public" in schemas.json()["schemas"]

        analyzed = client.post(
            f"/api/v1/targets/{target_id}/analyze",
            json={"schemas": ["public"]},
        )
        assert analyzed.status_code == 200, analyzed.text
        payload = analyzed.json()
        assert payload["status"] == "SUCCESS"
        assert payload["tables"] > 0
        _assert_no_secret_leak(payload, password)
    finally:
        _delete_target(target_id)


def test_request_password_overrides_saved(client: TestClient):
    name = f"ovr_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/v1/targets",
        json=_target_payload(name, password="wrong-saved-password"),
    )
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    try:
        # Wrong saved password would fail; request password wins
        probed = client.post(
            f"/api/v1/targets/{target_id}/test",
            json={"password": _medical_password()},
        )
        assert probed.status_code == 200, probed.text
        assert probed.json()["connected"] is True
    finally:
        _delete_target(target_id)


def test_missing_password_returns_400(client: TestClient):
    name = f"nopw_{uuid.uuid4().hex[:8]}"
    client.get("/api/v1/targets")  # bootstrap
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.begin() as conn:
        source_id = conn.execute(
            text(
                """
                INSERT INTO catalog_source (
                    source_name, db_type, host, port, database_name,
                    default_schema, username, encrypted_password, enabled
                ) VALUES (
                    :name, 'postgresql', 'localhost', 5432, 'demo',
                    'public', 'u', NULL, TRUE
                ) RETURNING id
                """
            ),
            {"name": name},
        ).scalar_one()
    try:
        for path in ("test", "schemas"):
            resp = client.post(f"/api/v1/targets/{source_id}/{path}", json={})
            assert resp.status_code == 400, resp.text
        resp = client.post(
            f"/api/v1/targets/{source_id}/analyze",
            json={"schemas": ["public"]},
        )
        assert resp.status_code == 400, resp.text
    finally:
        _delete_target(source_id)


def test_target_test_schemas_analyze_and_summary(client: TestClient):
    name = f"analyze_{uuid.uuid4().hex[:8]}"
    password = _medical_password()
    create = client.post("/api/v1/targets", json=_target_payload(name, password=password))
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    try:
        probed = client.post(
            f"/api/v1/targets/{target_id}/test", json={"password": password}
        )
        assert probed.status_code == 200, probed.text
        assert probed.json()["connected"] is True
        assert "PostgreSQL" in probed.json()["dbms_product"]

        schemas = client.post(
            f"/api/v1/targets/{target_id}/schemas", json={"password": password}
        )
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
        assert password not in str(payload)

        tables = client.get(f"/api/v1/schema/tables?source_id={target_id}")
        assert tables.status_code == 200
        assert len(tables.json()) == payload["tables"]

        summary = client.get(f"/api/v1/targets/{target_id}/catalog-summary")
        assert summary.status_code == 200, summary.text
        summary_body = summary.json()
        assert summary_body["tables"] == payload["tables"]
        assert summary_body["last_success_fingerprint"]
    finally:
        _delete_target(target_id)


def test_medical_demo_analyze_still_works(client: TestClient):
    response = client.post("/api/v1/schema/analyze")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["source"] == "medical_demo"


def test_password_column_not_plaintext_on_source(client: TestClient):
    client.get("/api/v1/targets")  # bootstrap migration
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
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
    assert "encrypted_password" in cols
    assert "username" in cols


def test_delete_target_cascades_and_preserves_others(client: TestClient):
    keep_name = f"keep_{uuid.uuid4().hex[:8]}"
    drop_name = f"drop_{uuid.uuid4().hex[:8]}"
    password = _medical_password()
    keep = client.post("/api/v1/targets", json=_target_payload(keep_name, password=password))
    drop = client.post("/api/v1/targets", json=_target_payload(drop_name, password=password))
    assert keep.status_code == 201, keep.text
    assert drop.status_code == 201, drop.text
    keep_id = keep.json()["id"]
    drop_id = drop.json()["id"]
    try:
        analyzed = client.post(
            f"/api/v1/targets/{drop_id}/analyze",
            json={"schemas": ["public"]},
        )
        assert analyzed.status_code == 200, analyzed.text
        assert analyzed.json()["status"] == "SUCCESS"

        # Build docs for drop target so delete must clean search docs
        rebuild = client.post(
            f"/api/v1/embeddings/documents/rebuild?source={drop_name}",
            timeout=120,
        )
        assert rebuild.status_code == 200, rebuild.text

        engine = create_engine(_catalog_url(), pool_pre_ping=True)
        with engine.connect() as conn:
            tables_before = conn.execute(
                text("SELECT count(*) FROM catalog_table WHERE source_id = :sid"),
                {"sid": drop_id},
            ).scalar_one()
            docs_before = conn.execute(
                text(
                    "SELECT count(*) FROM catalog_search_document WHERE source_id = :sid"
                ),
                {"sid": drop_id},
            ).scalar_one()
        assert tables_before > 0
        assert docs_before > 0

        deleted = client.delete(f"/api/v1/targets/{drop_id}")
        assert deleted.status_code == 204, deleted.text

        listed = client.get("/api/v1/targets")
        ids = {t["id"] for t in listed.json()}
        assert drop_id not in ids
        assert keep_id in ids

        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT count(*) FROM catalog_source WHERE id = :sid"),
                    {"sid": drop_id},
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text("SELECT count(*) FROM catalog_table WHERE source_id = :sid"),
                    {"sid": drop_id},
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM catalog_analysis_run WHERE source_id = :sid"
                    ),
                    {"sid": drop_id},
                ).scalar_one()
                == 0
            )
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM catalog_search_document WHERE source_id = :sid"
                    ),
                    {"sid": drop_id},
                ).scalar_one()
                == 0
            )
            # Other target preserved
            assert (
                conn.execute(
                    text("SELECT count(*) FROM catalog_source WHERE id = :sid"),
                    {"sid": keep_id},
                ).scalar_one()
                == 1
            )
    finally:
        _delete_target(keep_id)
        # drop may already be gone
        engine = create_engine(_catalog_url(), pool_pre_ping=True)
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT id FROM catalog_source WHERE id = :sid"),
                {"sid": drop_id},
            ).first()
        if exists:
            _delete_target(drop_id)


def test_delete_missing_target_404(client: TestClient):
    resp = client.delete("/api/v1/targets/99999999")
    assert resp.status_code == 404


def test_create_requires_password(client: TestClient):
    name = f"reqpw_{uuid.uuid4().hex[:8]}"
    payload = _target_payload(name)
    del payload["password"]
    resp = client.post("/api/v1/targets", json=payload)
    assert resp.status_code == 422, resp.text
