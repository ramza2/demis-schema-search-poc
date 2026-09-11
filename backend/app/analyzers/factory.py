"""Factory for DBMS-specific schema inspectors."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from app.analyzers.base import SchemaInspector
from app.analyzers.mariadb import MariaDBSchemaInspector
from app.analyzers.mysql import MySQLSchemaInspector
from app.analyzers.oracle import OracleSchemaInspector
from app.analyzers.postgres import PostgreSQLSchemaInspector


def create_schema_inspector(
    db_type: str, engine: Engine, database_name: str
) -> SchemaInspector:
    """Return a SchemaInspector for the given DBMS type."""
    normalized = (db_type or "").strip().lower()
    if normalized in ("postgresql", "postgres"):
        return PostgreSQLSchemaInspector(engine, database_name)
    if normalized == "mysql":
        return MySQLSchemaInspector(engine, database_name)
    if normalized == "mariadb":
        return MariaDBSchemaInspector(engine, database_name)
    if normalized == "oracle":
        return OracleSchemaInspector(engine, database_name)
    raise ValueError(f"Unsupported db_type for schema inspection: {db_type}")
