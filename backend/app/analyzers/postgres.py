"""PostgreSQL schema inspector (metadata SELECT only)."""

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

SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")


class PostgreSQLSchemaInspector(SchemaInspector):
    def __init__(self, engine: Engine, database_name: str) -> None:
        self._engine = engine
        self._database_name = database_name

    def list_schemas(self) -> list[str]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT nspname
                    FROM pg_catalog.pg_namespace
                    WHERE nspname NOT LIKE 'pg_%'
                      AND nspname <> 'information_schema'
                    ORDER BY 1
                    """
                )
            ).mappings()
        return [
            str(r["nspname"])
            for r in rows
            if r["nspname"] not in SYSTEM_SCHEMAS
        ]

    def inspect(self, schema_name: str = "public") -> SchemaSnapshot:
        if schema_name in SYSTEM_SCHEMAS:
            raise ValueError(f"System schema is not analyzable: {schema_name}")

        with self._engine.connect() as conn:
            # Read-only metadata queries only — no business row data.
            tables = self._fetch_tables(conn, schema_name)
            columns = self._fetch_columns(conn, schema_name)
            primary_keys = self._fetch_primary_keys(conn, schema_name)
            unique_constraints = self._fetch_unique_constraints(conn, schema_name)
            foreign_keys = self._fetch_foreign_keys(conn, schema_name)
            indexes = self._fetch_indexes(conn, schema_name)

        return SchemaSnapshot(
            db_type="postgresql",
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
                SELECT c.relname AS table_name,
                       CASE c.relkind
                           WHEN 'r' THEN 'BASE TABLE'
                           WHEN 'p' THEN 'PARTITIONED TABLE'
                           WHEN 'v' THEN 'VIEW'
                           ELSE c.relkind::text
                       END AS table_type,
                       obj_description(c.oid, 'pg_class') AS table_comment
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :schema
                  AND c.relkind IN ('r', 'p')
                  AND c.relname NOT LIKE 'pg_%'
                ORDER BY c.relname
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedTable(
                schema_name=schema_name,
                table_name=r["table_name"],
                table_type=r["table_type"],
                table_comment=r["table_comment"],
            )
            for r in rows
        ]

    def _fetch_columns(self, conn, schema_name: str) -> list[InspectedColumn]:
        rows = conn.execute(
            text(
                """
                SELECT c.table_schema,
                       c.table_name,
                       c.ordinal_position,
                       c.column_name,
                       c.data_type,
                       c.character_maximum_length,
                       c.numeric_precision,
                       c.numeric_scale,
                       (c.is_nullable = 'YES') AS is_nullable,
                       c.column_default AS default_value,
                       pgd.description AS column_comment
                FROM information_schema.columns c
                JOIN pg_catalog.pg_class cls
                  ON cls.relname = c.table_name
                JOIN pg_catalog.pg_namespace nsp
                  ON nsp.oid = cls.relnamespace AND nsp.nspname = c.table_schema
                JOIN pg_catalog.pg_attribute attr
                  ON attr.attrelid = cls.oid
                 AND attr.attname = c.column_name
                 AND attr.attnum > 0
                 AND NOT attr.attisdropped
                LEFT JOIN pg_catalog.pg_description pgd
                  ON pgd.objoid = cls.oid AND pgd.objsubid = attr.attnum
                WHERE c.table_schema = :schema
                ORDER BY c.table_name, c.ordinal_position
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedColumn(
                schema_name=r["table_schema"],
                table_name=r["table_name"],
                ordinal_position=int(r["ordinal_position"]),
                column_name=r["column_name"],
                data_type=r["data_type"],
                character_maximum_length=r["character_maximum_length"],
                numeric_precision=r["numeric_precision"],
                numeric_scale=r["numeric_scale"],
                is_nullable=bool(r["is_nullable"]),
                default_value=r["default_value"],
                column_comment=r["column_comment"],
            )
            for r in rows
        ]

    def _fetch_primary_keys(self, conn, schema_name: str) -> list[InspectedPrimaryKey]:
        rows = conn.execute(
            text(
                """
                SELECT tc.table_schema,
                       tc.table_name,
                       tc.constraint_name,
                       kcu.column_name,
                       kcu.ordinal_position
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                 AND tc.table_name = kcu.table_name
                WHERE tc.table_schema = :schema
                  AND tc.constraint_type = 'PRIMARY KEY'
                ORDER BY tc.table_name, kcu.ordinal_position
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedPrimaryKey(
                schema_name=r["table_schema"],
                table_name=r["table_name"],
                constraint_name=r["constraint_name"],
                column_name=r["column_name"],
                ordinal_position=int(r["ordinal_position"]),
            )
            for r in rows
        ]

    def _fetch_unique_constraints(self, conn, schema_name: str) -> list[InspectedUniqueConstraint]:
        rows = conn.execute(
            text(
                """
                SELECT tc.table_schema,
                       tc.table_name,
                       tc.constraint_name,
                       kcu.column_name,
                       kcu.ordinal_position
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                 AND tc.table_name = kcu.table_name
                WHERE tc.table_schema = :schema
                  AND tc.constraint_type = 'UNIQUE'
                ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedUniqueConstraint(
                schema_name=r["table_schema"],
                table_name=r["table_name"],
                constraint_name=r["constraint_name"],
                column_name=r["column_name"],
                ordinal_position=int(r["ordinal_position"]),
            )
            for r in rows
        ]

    def _fetch_foreign_keys(self, conn, schema_name: str) -> list[InspectedForeignKey]:
        rows = conn.execute(
            text(
                """
                SELECT con.conname AS constraint_name,
                       src_ns.nspname AS source_schema,
                       src_cls.relname AS source_table,
                       tgt_ns.nspname AS target_schema,
                       tgt_cls.relname AS target_table,
                       src_att.attname AS source_column,
                       tgt_att.attname AS target_column,
                       ord.ordinality AS ordinal_position
                FROM pg_catalog.pg_constraint con
                JOIN pg_catalog.pg_class src_cls ON src_cls.oid = con.conrelid
                JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src_cls.relnamespace
                JOIN pg_catalog.pg_class tgt_cls ON tgt_cls.oid = con.confrelid
                JOIN pg_catalog.pg_namespace tgt_ns ON tgt_ns.oid = tgt_cls.relnamespace
                JOIN LATERAL unnest(con.conkey, con.confkey)
                     WITH ORDINALITY AS ord(src_attnum, tgt_attnum, ordinality) ON TRUE
                JOIN pg_catalog.pg_attribute src_att
                  ON src_att.attrelid = con.conrelid AND src_att.attnum = ord.src_attnum
                JOIN pg_catalog.pg_attribute tgt_att
                  ON tgt_att.attrelid = con.confrelid AND tgt_att.attnum = ord.tgt_attnum
                WHERE con.contype = 'f'
                  AND src_ns.nspname = :schema
                ORDER BY con.conname, ord.ordinality
                """
            ),
            {"schema": schema_name},
        ).mappings()

        grouped: dict[str, dict] = {}
        for r in rows:
            key = r["constraint_name"]
            if key not in grouped:
                grouped[key] = {
                    "schema_name": r["source_schema"],
                    "constraint_name": r["constraint_name"],
                    "source_table": r["source_table"],
                    "target_schema": r["target_schema"],
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
                SELECT n.nspname AS schema_name,
                       t.relname AS table_name,
                       i.relname AS index_name,
                       ix.indisunique AS is_unique,
                       am.amname AS index_method,
                       pg_get_indexdef(ix.indexrelid) AS index_definition,
                       a.attname AS column_name,
                       ord.ordinality AS ordinal_position
                FROM pg_catalog.pg_index ix
                JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
                JOIN pg_catalog.pg_class t ON t.oid = ix.indrelid
                JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_catalog.pg_am am ON am.oid = i.relam
                JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS ord(attnum, ordinality) ON TRUE
                JOIN pg_catalog.pg_attribute a
                  ON a.attrelid = t.oid AND a.attnum = ord.attnum
                WHERE n.nspname = :schema
                  AND NOT ix.indisprimary
                  AND t.relkind IN ('r', 'p')
                ORDER BY t.relname, i.relname, ord.ordinality
                """
            ),
            {"schema": schema_name},
        ).mappings()

        grouped: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["table_name"], r["index_name"])
            if key not in grouped:
                grouped[key] = {
                    "schema_name": r["schema_name"],
                    "table_name": r["table_name"],
                    "index_name": r["index_name"],
                    "is_unique": bool(r["is_unique"]),
                    "index_method": r["index_method"],
                    "index_definition": r["index_definition"],
                    "columns": [],
                }
            grouped[key]["columns"].append(
                InspectedIndexColumn(
                    ordinal_position=int(r["ordinal_position"]),
                    column_name=r["column_name"],
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
