"""Target DB connect timeout, host validation, and bounded failure tests."""

from __future__ import annotations

import inspect
import os
import time
import uuid
from unittest.mock import MagicMock

import oracledb
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.db.target_connection import (
    HOST_VALIDATION_MESSAGE,
    TargetConnectionInfo,
    build_connect_args,
    create_target_engine,
    mask_secrets,
    validate_target_host,
)


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def _delete_target(source_id: int) -> None:
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
    os.environ["TARGET_DB_CONNECT_TIMEOUT_SECONDS"] = "2"

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.mark.parametrize(
    "db_type,expected_key",
    [
        ("postgresql", "connect_timeout"),
        ("mysql", "connect_timeout"),
        ("mariadb", "connect_timeout"),
        ("oracle", "tcp_connect_timeout"),
    ],
)
def test_build_connect_args_per_dbms(db_type: str, expected_key: str):
    args = build_connect_args(db_type, 5)
    assert expected_key in args
    if db_type == "postgresql":
        assert args == {"connect_timeout": 5}
    elif db_type in {"mysql", "mariadb"}:
        assert args["connect_timeout"] == 5
        assert args["read_timeout"] == 5
        assert args["write_timeout"] == 5
    else:
        assert args == {"tcp_connect_timeout": 5.0}


def test_oracle_tcp_connect_timeout_in_driver_signature():
    sig = inspect.signature(oracledb.connect)
    assert "tcp_connect_timeout" in sig.parameters


def test_create_engine_passes_connect_timeout_postgresql(monkeypatch):
    captured: dict = {}

    def fake_create_engine(url, **kwargs):  # noqa: ANN001
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("app.db.target_connection.create_engine", fake_create_engine)
    info = TargetConnectionInfo(
        db_type="postgresql",
        host="db.example.com",
        port=5432,
        database_name="demo",
        username="u",
    )
    create_target_engine(info, "secret", connect_timeout_seconds=7)
    assert captured["kwargs"]["pool_pre_ping"] is True
    assert captured["kwargs"]["connect_args"] == {"connect_timeout": 7}


def test_create_engine_passes_connect_timeout_mysql(monkeypatch):
    captured: dict = {}

    def fake_create_engine(url, **kwargs):  # noqa: ANN001
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("app.db.target_connection.create_engine", fake_create_engine)
    info = TargetConnectionInfo(
        db_type="mysql",
        host="db.example.com",
        port=3306,
        database_name="demo",
        username="u",
    )
    create_target_engine(info, "secret", connect_timeout_seconds=4)
    assert captured["kwargs"]["connect_args"]["connect_timeout"] == 4
    assert captured["kwargs"]["connect_args"]["read_timeout"] == 4


def test_create_engine_passes_oracle_tcp_timeout(monkeypatch):
    captured: dict = {}

    def fake_create_engine(url, **kwargs):  # noqa: ANN001
        captured["kwargs"] = kwargs
        return MagicMock()

    monkeypatch.setattr("app.db.target_connection.create_engine", fake_create_engine)
    info = TargetConnectionInfo(
        db_type="oracle",
        host="ora.example.com",
        port=1521,
        database_name="ORCL",
        username="u",
        connection_options={"service_name": "ORCL"},
    )
    create_target_engine(info, "secret", connect_timeout_seconds=5)
    assert captured["kwargs"]["connect_args"] == {"tcp_connect_timeout": 5.0}


@pytest.mark.parametrize(
    "host",
    [
        "http://example.com",
        "https://example.com",
        "://azure.com",
        "db.example.com/path",
        "",
        "   ",
    ],
)
def test_validate_target_host_rejects(host: str):
    with pytest.raises(ValueError) as exc_info:
        validate_target_host(host)
    assert str(exc_info.value) == HOST_VALIDATION_MESSAGE


@pytest.mark.parametrize(
    "host",
    [
        "db.example.com",
        "postgres.example.internal",
        "192.168.0.10",
        "10.0.0.5",
        "localhost",
        "::1",
        "2001:db8::1",
        "[2001:db8::1]",
    ],
)
def test_validate_target_host_allows(host: str):
    assert validate_target_host(host) == host.strip()


def test_create_target_rejects_http_host(client: TestClient):
    resp = client.post(
        "/api/v1/targets",
        json={
            "source_name": f"bad_{uuid.uuid4().hex[:8]}",
            "db_type": "postgresql",
            "host": "http://example.com",
            "port": 5432,
            "database_name": "demo",
            "default_schema": "public",
            "username": "u",
            "enabled": True,
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == HOST_VALIDATION_MESSAGE


def test_create_target_rejects_scheme_host(client: TestClient):
    resp = client.post(
        "/api/v1/targets",
        json={
            "source_name": f"bad_{uuid.uuid4().hex[:8]}",
            "db_type": "postgresql",
            "host": "://azure.com",
            "port": 5432,
            "database_name": "demo",
            "default_schema": "public",
            "username": "u",
            "enabled": True,
        },
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == HOST_VALIDATION_MESSAGE


def test_update_target_rejects_https_host(client: TestClient):
    name = f"upd_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/v1/targets",
        json={
            "source_name": name,
            "db_type": "postgresql",
            "host": "localhost",
            "port": 5432,
            "database_name": "demo",
            "default_schema": "public",
            "username": "u",
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    try:
        updated = client.put(
            f"/api/v1/targets/{target_id}",
            json={"host": "https://example.com"},
        )
        assert updated.status_code == 400, updated.text
        assert updated.json()["detail"] == HOST_VALIDATION_MESSAGE
    finally:
        _delete_target(target_id)


def test_password_masked_in_connection_errors():
    secret = "super-secret-password-xyz"
    msg = mask_secrets(f"could not connect with password {secret}", secret)
    assert secret not in msg
    assert "***" in msg


def test_test_connection_unreachable_host_bounded_timeout(client: TestClient):
    """Unreachable TEST-NET address must fail within ~timeout bound (not hang)."""
    name = f"timeout_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/api/v1/targets",
        json={
            "source_name": name,
            "db_type": "postgresql",
            "host": "192.0.2.1",  # TEST-NET-1, should not route
            "port": 5432,
            "database_name": "demo",
            "default_schema": "public",
            "username": "u",
            "enabled": True,
        },
    )
    assert create.status_code == 201, create.text
    target_id = create.json()["id"]
    password = "must-not-leak-password-value"
    try:
        started = time.monotonic()
        probed = client.post(
            f"/api/v1/targets/{target_id}/test",
            json={"password": password},
        )
        elapsed = time.monotonic() - started
        assert elapsed < 20, f"test connection took too long: {elapsed:.1f}s"
        assert probed.status_code in {502, 504}, probed.text
        detail = str(probed.json().get("detail", ""))
        assert password not in detail
        assert "postgresql+psycopg://" not in detail
        if probed.status_code == 504:
            assert "timed out" in detail.lower() or "timeout" in detail.lower()
    finally:
        _delete_target(target_id)
