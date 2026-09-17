"""Focused tests for DB analysis preflight readiness checks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import preflight_service as module
from app.services.preflight_service import PreflightService


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self):
        return _Connection()

    def dispose(self) -> None:
        self.disposed = True


class _TargetService:
    def __init__(self, *, password: str = "top-secret") -> None:
        self.password = password
        self.source = SimpleNamespace(
            id=7,
            source_name="oracle_demis_mock",
            db_type="oracle",
            host="oracle-mock",
            port=1521,
            database_name="FREEPDB1",
            username="DEMIS_OWNER",
            connection_options={"service_name": "FREEPDB1"},
            default_schema="DEMIS_OWNER",
            enabled=True,
        )

    def get_target(self, target_id: int):
        if target_id != 7:
            raise LookupError(f"target not found: {target_id}")
        return self.source

    def resolve_password(self, source, request_password: str | None) -> str:
        return self.password if request_password is None else request_password

    def _connect_timeout_seconds(self) -> float:
        return 5.0


class _Inspector:
    def __init__(self, *, discovery_error: bool = False, fk_error: bool = False) -> None:
        self.discovery_error = discovery_error
        self.fk_error = fk_error

    def list_schemas(self) -> list[str]:
        if self.discovery_error:
            raise PermissionError("schema list denied")
        return ["DEMIS_OWNER"]

    def _fetch_tables(self, conn, schema_name: str):
        assert schema_name == "DEMIS_OWNER"
        return [
            SimpleNamespace(table_comment="환자 기본 정보"),
            SimpleNamespace(table_comment=None),
        ]

    def _fetch_columns(self, conn, schema_name: str):
        return [
            SimpleNamespace(column_comment="환자 식별자"),
            SimpleNamespace(column_comment=None),
            SimpleNamespace(column_comment=None),
        ]

    def _fetch_primary_keys(self, conn, schema_name: str):
        return [object()]

    def _fetch_unique_constraints(self, conn, schema_name: str):
        return [object()]

    def _fetch_foreign_keys(self, conn, schema_name: str):
        if self.fk_error:
            raise PermissionError("ALL_CONSTRAINTS denied")
        return [object()]

    def _fetch_indexes(self, conn, schema_name: str):
        return [object(), object()]


def _install_successful_connection(monkeypatch: pytest.MonkeyPatch, inspector: _Inspector) -> _Engine:
    engine = _Engine()
    monkeypatch.setattr(module, "create_target_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(
        module,
        "probe_connection",
        lambda *args, **kwargs: {
            "connected": True,
            "dbms_product": "Oracle",
            "db_version": "Oracle Database 23ai Free",
            "database_or_service": "FREEPDB1",
            "current_user": "DEMIS_OWNER",
        },
    )
    monkeypatch.setattr(
        module,
        "create_schema_inspector",
        lambda *args, **kwargs: inspector,
    )
    return engine


def test_preflight_ready_collects_metadata_without_business_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _install_successful_connection(monkeypatch, _Inspector())
    service = PreflightService(target_service=_TargetService())

    result = service.run(7, schemas=["DEMIS_OWNER"])

    assert result.status == "READY"
    assert result.connection.dbms_product == "Oracle"
    assert result.summary.tables == 2
    assert result.summary.columns == 3
    assert result.summary.primary_keys == 1
    assert result.summary.unique_constraints == 1
    assert result.summary.foreign_keys == 1
    assert result.summary.indexes == 2
    assert result.summary.table_comments == 1
    assert result.summary.column_comments == 1
    assert result.summary.blocked == 0
    assert result.security.metadata_select_only is True
    assert result.security.business_data_selected is False
    assert result.security.credentials_returned is False
    assert any(check.key == "SAFETY_MODE" and check.status == "PASS" for check in result.checks)
    assert engine.disposed is True


def test_preflight_schema_discovery_failure_is_warning_when_direct_metadata_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_successful_connection(monkeypatch, _Inspector(discovery_error=True))
    service = PreflightService(target_service=_TargetService())

    result = service.run(7, schemas=["DEMIS_OWNER"])

    assert result.status == "WARNING"
    discovery = next(check for check in result.checks if check.key == "SCHEMA_DISCOVERY")
    assert discovery.status == "WARNING"
    assert result.summary.blocked == 0
    assert result.summary.tables == 2


def test_preflight_metadata_permission_failure_blocks_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_successful_connection(monkeypatch, _Inspector(fk_error=True))
    service = PreflightService(target_service=_TargetService())

    result = service.run(7, schemas=["DEMIS_OWNER"])

    assert result.status == "BLOCKED"
    fk_check = next(check for check in result.checks if check.key == "FK_METADATA")
    assert fk_check.status == "BLOCKED"
    assert "ALL_CONSTRAINTS denied" in fk_check.detail
    assert result.summary.blocked >= 1


def test_preflight_connection_failure_is_blocked_and_redacts_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "dont-leak-me"

    def _fail_engine(*args, **kwargs):
        raise RuntimeError(f"oracle://DEMIS_OWNER:{secret}@oracle-mock/FREEPDB1")

    monkeypatch.setattr(module, "create_target_engine", _fail_engine)
    service = PreflightService(target_service=_TargetService(password=secret))

    result = service.run(7, schemas=["DEMIS_OWNER"])

    assert result.status == "BLOCKED"
    connection = next(check for check in result.checks if check.key == "CONNECTION")
    assert secret not in connection.detail
    assert result.security.credentials_returned is False
