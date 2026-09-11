"""Package marker for DBMS schema inspectors."""

from app.analyzers.base import SchemaInspector, SchemaSnapshot, merge_snapshots
from app.analyzers.factory import create_schema_inspector
from app.analyzers.mariadb import MariaDBSchemaInspector
from app.analyzers.mysql import MySQLSchemaInspector
from app.analyzers.oracle import OracleSchemaInspector
from app.analyzers.postgres import PostgreSQLSchemaInspector

__all__ = [
    "SchemaInspector",
    "SchemaSnapshot",
    "merge_snapshots",
    "create_schema_inspector",
    "PostgreSQLSchemaInspector",
    "MySQLSchemaInspector",
    "MariaDBSchemaInspector",
    "OracleSchemaInspector",
]
