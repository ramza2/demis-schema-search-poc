"""Optional live Oracle smoke tests (skipped unless ORACLE_TEST_* env is set)."""

from __future__ import annotations

import os

import pytest

_ORACLE_REQUIRED = (
    "ORACLE_TEST_HOST",
    "ORACLE_TEST_PORT",
    "ORACLE_TEST_USER",
    "ORACLE_TEST_PASSWORD",
    "ORACLE_TEST_SERVICE",
)


def _oracle_env_ready() -> bool:
    return all(os.getenv(k) for k in _ORACLE_REQUIRED)


pytestmark = pytest.mark.skipif(
    not _oracle_env_ready(),
    reason="ORACLE_TEST_* environment variables not fully set",
)


def test_oracle_live_connection_list_schemas_and_inspect() -> None:
    from sqlalchemy import text

    from app.analyzers.oracle import OracleSchemaInspector
    from app.db.target_connection import (
        TargetConnectionInfo,
        create_target_engine,
        probe_connection,
    )

    host = os.environ["ORACLE_TEST_HOST"]
    port = int(os.environ["ORACLE_TEST_PORT"])
    user = os.environ["ORACLE_TEST_USER"]
    password = os.environ["ORACLE_TEST_PASSWORD"]
    service = os.environ["ORACLE_TEST_SERVICE"]
    schema = os.getenv("ORACLE_TEST_SCHEMA", user).upper()

    info = TargetConnectionInfo(
        db_type="oracle",
        host=host,
        port=port,
        database_name=service,
        username=user,
        connection_options={"service_name": service},
    )
    engine = create_target_engine(info, password)
    probe = probe_connection(engine, "oracle")
    assert probe["connected"] is True
    assert probe["dbms_product"] == "Oracle"

    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM dual"))

    inspector = OracleSchemaInspector(engine, service)
    schemas = inspector.list_schemas()
    assert isinstance(schemas, list)
    # Owner may or may not appear depending on grants; inspect when present.
    if schema in schemas or schema.upper() in {s.upper() for s in schemas}:
        target = next(s for s in schemas if s.upper() == schema.upper())
        snap = inspector.inspect(target)
        assert snap.db_type == "oracle"
        assert snap.schema_name == target
        assert isinstance(snap.tables, list)
        assert isinstance(snap.columns, list)
        assert isinstance(snap.primary_keys, list)
        assert isinstance(snap.foreign_keys, list)
        assert isinstance(snap.indexes, list)
