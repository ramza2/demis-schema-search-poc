"""Passwordless Target credential semantics (None vs empty string vs clear)."""

from __future__ import annotations

import os
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.db.target_connection import TargetConnectionInfo, build_target_url
from app.models.catalog import CatalogSource
from app.schemas.target_api import TargetCreate, TargetUpdate
from app.security.credential_crypto import decrypt_password, encrypt_password
from app.services.target_service import TargetService


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
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM catalog_source WHERE id = :sid"),
            {"sid": source_id},
        )


@pytest.fixture()
def client():
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))
    _ensure_encryption_key()

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        yield test_client


def _passwordless_payload(name: str) -> dict:
    return {
        "source_name": name,
        "db_type": "mysql",
        "host": "db.example.test",
        "port": 3306,
        "database_name": "demo",
        "default_schema": "demo",
        "username": "anonymous",
        "password": "",
        "connection_options": None,
        "enabled": True,
    }


def _stored_ciphertext(source_id: int) -> str | None:
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT encrypted_password FROM catalog_source WHERE id = :sid"),
            {"sid": source_id},
        ).scalar_one()


def test_target_create_schema_accepts_empty_password() -> None:
    payload = TargetCreate(**_passwordless_payload("schema_only"))
    assert payload.password == ""


def test_target_update_semantics_distinguish_empty_none_and_clear() -> None:
    empty = TargetUpdate(password="")
    assert empty.model_dump(exclude_unset=True)["password"] == ""

    null_value = TargetUpdate(password=None)
    assert null_value.model_dump(exclude_unset=True)["password"] is None

    with pytest.raises(ValidationError, match="password and clear_saved_password"):
        TargetUpdate(password="", clear_saved_password=True)


def test_resolve_password_accepts_explicit_and_saved_empty_password() -> None:
    key = Fernet.generate_key().decode()
    service = TargetService(Settings(target_credential_encryption_key=key))
    source = CatalogSource(encrypted_password=encrypt_password("", key))

    assert service.resolve_password(source, "") == ""
    assert service.resolve_password(source, None) == ""


def test_resolve_password_without_request_or_saved_credential_still_fails() -> None:
    key = Fernet.generate_key().decode()
    service = TargetService(Settings(target_credential_encryption_key=key))
    source = CatalogSource(encrypted_password=None)

    with pytest.raises(ValueError, match="Password is required"):
        service.resolve_password(source, None)


def test_mysql_url_supports_passwordless_account() -> None:
    info = TargetConnectionInfo(
        db_type="mysql",
        host="db.example.test",
        port=3306,
        database_name="demo",
        username="anonymous",
    )
    url = build_target_url(info, "")
    assert url == "mysql+pymysql://anonymous:@db.example.test:3306/demo?charset=utf8mb4"


def test_api_create_passwordless_target_stores_encrypted_empty_credential(
    client: TestClient,
) -> None:
    key = _ensure_encryption_key()
    name = f"pwless_{uuid.uuid4().hex[:8]}"
    created = client.post("/api/v1/targets", json=_passwordless_payload(name))
    assert created.status_code == 201, created.text
    body = created.json()
    target_id = body["id"]
    try:
        assert body["has_saved_password"] is True
        assert "password" not in body
        assert "encrypted_password" not in body

        ciphertext = _stored_ciphertext(target_id)
        assert ciphertext
        assert decrypt_password(ciphertext, key) == ""
    finally:
        _delete_target(target_id)


def test_api_update_empty_password_replaces_existing_credential(
    client: TestClient,
) -> None:
    key = _ensure_encryption_key()
    name = f"pwless_update_{uuid.uuid4().hex[:8]}"
    payload = _passwordless_payload(name)
    payload["password"] = "non-empty-before"
    created = client.post("/api/v1/targets", json=payload)
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    try:
        before = _stored_ciphertext(target_id)
        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"password": ""},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True

        after = _stored_ciphertext(target_id)
        assert after
        assert after != before
        assert decrypt_password(after, key) == ""
    finally:
        _delete_target(target_id)


def test_api_update_explicit_null_keeps_existing_credential(client: TestClient) -> None:
    name = f"pwless_null_{uuid.uuid4().hex[:8]}"
    payload = _passwordless_payload(name)
    payload["password"] = "keep-me"
    created = client.post("/api/v1/targets", json=payload)
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    try:
        before = _stored_ciphertext(target_id)
        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"password": None},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["has_saved_password"] is True
        assert _stored_ciphertext(target_id) == before
    finally:
        _delete_target(target_id)


def test_api_clear_saved_password_removes_credential(client: TestClient) -> None:
    name = f"pwless_clear_{uuid.uuid4().hex[:8]}"
    created = client.post("/api/v1/targets", json=_passwordless_payload(name))
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    try:
        cleared = client.put(
            f"/api/v1/targets/{target_id}",
            json={"clear_saved_password": True},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["has_saved_password"] is False
        assert _stored_ciphertext(target_id) is None
    finally:
        _delete_target(target_id)


def test_api_rejects_clear_and_explicit_empty_password_together(client: TestClient) -> None:
    name = f"pwless_conflict_{uuid.uuid4().hex[:8]}"
    created = client.post("/api/v1/targets", json=_passwordless_payload(name))
    assert created.status_code == 201, created.text
    target_id = created.json()["id"]
    try:
        response = client.put(
            f"/api/v1/targets/{target_id}",
            json={"password": "", "clear_saved_password": True},
        )
        assert response.status_code == 422, response.text
    finally:
        _delete_target(target_id)
