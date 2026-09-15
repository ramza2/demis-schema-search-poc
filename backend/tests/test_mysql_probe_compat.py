"""Compatibility tests for MySQL/MariaDB connection probing."""

from __future__ import annotations

from contextlib import nullcontext

from app.db.target_connection import probe_connection


class _FakeResult:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> _FakeResult:
        return self

    def one(self) -> dict[str, object]:
        return self._row


class _FakeConnection:
    def __init__(self) -> None:
        self.sql = ""

    def execute(self, statement):  # noqa: ANN001
        self.sql = str(statement)
        return _FakeResult(
            {
                "version": "5.6.0-test",
                "database_name": "Rfam",
                "authenticated_user": "rfamro@%",
            }
        )


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    def connect(self):
        return nullcontext(self.connection)


def test_mysql_probe_avoids_current_user_alias_keyword() -> None:
    engine = _FakeEngine()

    result = probe_connection(engine, "mysql")

    assert result == {
        "connected": True,
        "dbms_product": "MySQL",
        "db_version": "5.6.0-test",
        "database_or_service": "Rfam",
        "current_user": "rfamro@%",
    }
    assert "CURRENT_USER() AS authenticated_user" in engine.connection.sql
    assert "CURRENT_USER() AS current_user" not in engine.connection.sql
