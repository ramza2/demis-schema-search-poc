"""Shared MySQL / MariaDB schema inspector (information_schema, SELECT only)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.analyzers.base import (
    InspectedColumn,
    InspectedForeignKey,
    InspectedForeignKeyColumn,
    InspectedIndex,
    InspectedIndexColumn,
    InspectedPrimaryKey,
    InspectedTable,
    InspectedUniqueConstraint,
    SchemaInspector,
    SchemaSnapshot,
)

SYSTEM_SCHEMAS = (
    "information_schema",
    "mysql",
    "performance_schema",
    "sys",
)


class MySQLFamilySchemaInspector(SchemaInspector):
    def __init__(self, engine: Engine, database_name: str, db_type: str) -> None:
        if db_type not in ("mysql", "mariadb"):
            raise ValueError(f"Unsupported MySQL-family db_type: {db_type}")
        self._engine = engine
        self._database_name = database_name
        self._db_type = db_type

    def list_schemas(self) -> list[str]:
        placeholders = ", ".join(f":s{i}" for i in range(len(SYSTEM_SCHEMAS)))
        params = {f"s{i}": name for i, name in enumerate(SYSTEM_SCHEMAS)}
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT SCHEMA_NAME
                    FROM information_schema.SCHEMATA
                    WHERE SCHEMA_NAME NOT IN ({placeholders})
                    ORDER BY 1
                    """
                ),
                params,
            ).mappings()
        return [r["SCHEMA_NAME"] for r in rows]

    def inspect(self, schema_name: str = "public") -> SchemaSnapshot:
        if schema_name in SYSTEM_SCHEMAS:
            raise ValueError(f"System schema is not analyzable: {schema_name}")

        with self._engine.connect() as conn:
            tables = self._fetch_tables(conn, schema_name)
            columns = self._fetch_columns(conn, schema_name)
            primary_keys = self._fetch_primary_keys(conn, schema_name)
            unique_constraints = self._fetch_unique_constraints(conn, schema_name)
            foreign_keys = self._fetch_foreign_keys(conn, schema_name)
            indexes = self._fetch_indexes(conn, schema_name)

        return SchemaSnapshot(
            db_type=self._db_type,
            database_name=self._database_name,
            schema_name=schema_name,
            tables=tables,
            columns=columns,
            primary_keys=primary_keys,
            unique_constraints=unique_constraints,
            foreign_keys=foreign_keys,
            indexes=indexes,
        )

    def _fetch_tables(self, conn, schema_name: str) -> list[InspectedTable]:
        rows = conn.execute(
            text(
                """
                SELECT TABLE_NAME,
                       TABLE_TYPE,
                       TABLE_COMMENT
                FROM information_schema.TABLES
                WHERE TABLE_SCHEMA = :schema
                  AND TABLE_TYPE = 'BASE TABLE'
                ORDER BY TABLE_NAME
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedTable(
                schema_name=schema_name,
                table_name=r["TABLE_NAME"],
                table_type=r["TABLE_TYPE"] or "BASE TABLE",
                table_comment=r["TABLE_COMMENT"] or None,
            )
            for r in rows
        ]

    def _fetch_columns(self, conn, schema_name: str) -> list[InspectedColumn]:
        rows = conn.execute(
            text(
                """
                SELECT TABLE_SCHEMA,
                       TABLE_NAME,
                       ORDINAL_POSITION,
                       COLUMN_NAME,
                       DATA_TYPE,
                       CHARACTER_MAXIMUM_LENGTH,
                       NUMERIC_PRECISION,
                       NUMERIC_SCALE,
                       IS_NULLABLE,
                       COLUMN_DEFAULT,
                       COLUMN_COMMENT
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = :schema
                ORDER BY TABLE_NAME, ORDINAL_POSITION
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedColumn(
                schema_name=r["TABLE_SCHEMA"],
                table_name=r["TABLE_NAME"],
                ordinal_position=int(r["ORDINAL_POSITION"]),
                column_name=r["COLUMN_NAME"],
                data_type=r["DATA_TYPE"] or "",
                character_maximum_length=(
                    int(r["CHARACTER_MAXIMUM_LENGTH"])
                    if r["CHARACTER_MAXIMUM_LENGTH"] is not None
                    else None
                ),
                numeric_precision=(
                    int(r["NUMERIC_PRECISION"]) if r["NUMERIC_PRECISION"] is not None else None
                ),
                numeric_scale=(
                    int(r["NUMERIC_SCALE"]) if r["NUMERIC_SCALE"] is not None else None
                ),
                is_nullable=str(r["IS_NULLABLE"]).upper() == "YES",
                default_value=r["COLUMN_DEFAULT"],
                column_comment=r["COLUMN_COMMENT"] or None,
            )
            for r in rows
        ]

    def _fetch_primary_keys(self, conn, schema_name: str) -> list[InspectedPrimaryKey]:
        rows = conn.execute(
            text(
                """
                SELECT tc.TABLE_SCHEMA,
                       tc.TABLE_NAME,
                       tc.CONSTRAINT_NAME,
                       kcu.COLUMN_NAME,
                       kcu.ORDINAL_POSITION
                FROM information_schema.TABLE_CONSTRAINTS tc
                JOIN information_schema.KEY_COLUMN_USAGE kcu
                  ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
                 AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                 AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                 AND tc.TABLE_NAME = kcu.TABLE_NAME
                WHERE tc.TABLE_SCHEMA = :schema
                  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ORDER BY tc.TABLE_NAME, kcu.ORDINAL_POSITION
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedPrimaryKey(
                schema_name=r["TABLE_SCHEMA"],
                table_name=r["TABLE_NAME"],
                constraint_name=r["CONSTRAINT_NAME"],
                column_name=r["COLUMN_NAME"],
                ordinal_position=int(r["ORDINAL_POSITION"]),
            )
            for r in rows
        ]

    def _fetch_unique_constraints(self, conn, schema_name: str) -> list[InspectedUniqueConstraint]:
        rows = conn.execute(
            text(
                """
                SELECT tc.TABLE_SCHEMA,
                       tc.TABLE_NAME,
                       tc.CONSTRAINT_NAME,
                       kcu.COLUMN_NAME,
                       kcu.ORDINAL_POSITION
                FROM information_schema.TABLE_CONSTRAINTS tc
                JOIN information_schema.KEY_COLUMN_USAGE kcu
                  ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
                 AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                 AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                 AND tc.TABLE_NAME = kcu.TABLE_NAME
                WHERE tc.TABLE_SCHEMA = :schema
                  AND tc.CONSTRAINT_TYPE = 'UNIQUE'
                ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedUniqueConstraint(
                schema_name=r["TABLE_SCHEMA"],
                table_name=r["TABLE_NAME"],
                constraint_name=r["CONSTRAINT_NAME"],
                column_name=r["COLUMN_NAME"],
                ordinal_position=int(r["ORDINAL_POSITION"]),
            )
            for r in rows
        ]

    def _fetch_foreign_keys(self, conn, schema_name: str) -> list[InspectedForeignKey]:
        rows = conn.execute(
            text(
                """
                SELECT kcu.CONSTRAINT_NAME,
                       kcu.TABLE_SCHEMA AS source_schema,
                       kcu.TABLE_NAME AS source_table,
                       kcu.COLUMN_NAME AS source_column,
                       COALESCE(
                           kcu.REFERENCED_TABLE_SCHEMA,
                           rc.UNIQUE_CONSTRAINT_SCHEMA
                       ) AS target_schema,
                       kcu.REFERENCED_TABLE_NAME AS target_table,
                       kcu.REFERENCED_COLUMN_NAME AS target_column,
                       kcu.ORDINAL_POSITION AS ordinal_position
                FROM information_schema.KEY_COLUMN_USAGE kcu
                JOIN information_schema.TABLE_CONSTRAINTS tc
                  ON tc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
                 AND tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                 AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                 AND tc.TABLE_NAME = kcu.TABLE_NAME
                LEFT JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
                  ON rc.CONSTRAINT_SCHEMA = kcu.CONSTRAINT_SCHEMA
                 AND rc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
                WHERE kcu.TABLE_SCHEMA = :schema
                  AND tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
                ORDER BY kcu.CONSTRAINT_NAME, kcu.ORDINAL_POSITION
                """
            ),
            {"schema": schema_name},
        ).mappings()

        grouped: dict[str, dict] = {}
        for r in rows:
            key = r["CONSTRAINT_NAME"]
            if key not in grouped:
                grouped[key] = {
                    "schema_name": r["source_schema"],
                    "constraint_name": r["CONSTRAINT_NAME"],
                    "source_table": r["source_table"],
                    "target_schema": r["target_schema"] or schema_name,
                    "target_table": r["target_table"],
                    "columns": [],
                }
            grouped[key]["columns"].append(
                InspectedForeignKeyColumn(
                    ordinal_position=int(r["ordinal_position"]),
                    source_column=r["source_column"],
                    target_column=r["target_column"],
                )
            )

        result: list[InspectedForeignKey] = []
        for item in grouped.values():
            cols = tuple(sorted(item["columns"], key=lambda c: c.ordinal_position))
            result.append(
                InspectedForeignKey(
                    schema_name=item["schema_name"],
                    constraint_name=item["constraint_name"],
                    source_table=item["source_table"],
                    target_schema=item["target_schema"],
                    target_table=item["target_table"],
                    columns=cols,
                )
            )
        return sorted(result, key=lambda x: x.constraint_name)

    def _fetch_indexes(self, conn, schema_name: str) -> list[InspectedIndex]:
        rows = conn.execute(
            text(
                """
                SELECT TABLE_SCHEMA,
                       TABLE_NAME,
                       INDEX_NAME,
                       NON_UNIQUE,
                       INDEX_TYPE,
                       COLUMN_NAME,
                       SEQ_IN_INDEX
                FROM information_schema.STATISTICS
                WHERE TABLE_SCHEMA = :schema
                  AND INDEX_NAME <> 'PRIMARY'
                ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
                """
            ),
            {"schema": schema_name},
        ).mappings()

        grouped: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["TABLE_NAME"], r["INDEX_NAME"])
            if key not in grouped:
                grouped[key] = {
                    "schema_name": r["TABLE_SCHEMA"],
                    "table_name": r["TABLE_NAME"],
                    "index_name": r["INDEX_NAME"],
                    "is_unique": int(r["NON_UNIQUE"] or 0) == 0,
                    "index_method": r["INDEX_TYPE"],
                    "index_definition": None,
                    "columns": [],
                }
            grouped[key]["columns"].append(
                InspectedIndexColumn(
                    ordinal_position=int(r["SEQ_IN_INDEX"]),
                    column_name=r["COLUMN_NAME"],
                )
            )

        result: list[InspectedIndex] = []
        for item in grouped.values():
            cols = tuple(sorted(item["columns"], key=lambda c: c.ordinal_position))
            result.append(
                InspectedIndex(
                    schema_name=item["schema_name"],
                    table_name=item["table_name"],
                    index_name=item["index_name"],
                    is_unique=item["is_unique"],
                    index_method=item["index_method"],
                    index_definition=item["index_definition"],
                    columns=cols,
                )
            )
        return sorted(result, key=lambda x: (x.table_name, x.index_name))
