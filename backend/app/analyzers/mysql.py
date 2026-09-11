"""MySQL schema inspector."""

from __future__ import annotations

from sqlalchemy.engine import Engine

from app.analyzers.mysql_family import MySQLFamilySchemaInspector


class MySQLSchemaInspector(MySQLFamilySchemaInspector):
    def __init__(self, engine: Engine, database_name: str) -> None:
        super().__init__(engine, database_name, db_type="mysql")
