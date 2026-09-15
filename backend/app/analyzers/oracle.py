"""Oracle schema inspector using ALL_* views (metadata SELECT only)."""

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
    "SYS",
    "SYSTEM",
    "XDB",
    "CTXSYS",
    "MDSYS",
    "ORDDATA",
    "ORDSYS",
    "OUTLN",
    "DBSNMP",
    "APPQOSSYS",
    "WMSYS",
    "OLAPSYS",
    "GSMADMIN_INTERNAL",
    "LBACSYS",
    "DVSYS",
    "AUDSYS",
    "OJVMSYS",
    "ANONYMOUS",
    "DIP",
    "ORACLE_OCM",
    "REMOTE_SCHEDULER_AGENT",
    "SI_INFORMTN_SCHEMA",
    "SPATIAL_CSW_ADMIN_USR",
    "SPATIAL_WFS_ADMIN_USR",
    "SYSBACKUP",
    "SYSDG",
    "SYSKM",
    "SYSRAC",
    "XS$NULL",
    "GGSYS",
    "DGPDB_INT",
)


class OracleSchemaInspector(SchemaInspector):
    """Inspect Oracle schemas via ALL_* catalog views. Identifiers keep DB case."""

    def __init__(self, engine: Engine, database_name: str) -> None:
        self._engine = engine
        self._database_name = database_name

    def list_schemas(self) -> list[str]:
        placeholders = ", ".join(f":s{i}" for i in range(len(SYSTEM_SCHEMAS)))
        params = {f"s{i}": name for i, name in enumerate(SYSTEM_SCHEMAS)}
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT DISTINCT owner
                    FROM all_tables
                    WHERE owner NOT IN ({placeholders})
                    ORDER BY 1
                    """
                ),
                params,
            ).mappings()
        # Preserve physical case from the database; do not lowercase.
        return [r["owner"] for r in rows]

    def inspect(self, schema_name: str = "public") -> SchemaSnapshot:
        if schema_name.upper() in SYSTEM_SCHEMAS or schema_name in SYSTEM_SCHEMAS:
            raise ValueError(f"System schema is not analyzable: {schema_name}")

        with self._engine.connect() as conn:
            tables = self._fetch_tables(conn, schema_name)
            columns = self._fetch_columns(conn, schema_name)
            primary_keys = self._fetch_primary_keys(conn, schema_name)
            unique_constraints = self._fetch_unique_constraints(conn, schema_name)
            foreign_keys = self._fetch_foreign_keys(conn, schema_name)
            indexes = self._fetch_indexes(conn, schema_name)

        return SchemaSnapshot(
            db_type="oracle",
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
                SELECT t.owner AS schema_name,
                       t.table_name,
                       NVL(c.comments, NULL) AS table_comment
                FROM all_tables t
                LEFT JOIN all_tab_comments c
                  ON c.owner = t.owner
                 AND c.table_name = t.table_name
                 AND c.table_type = 'TABLE'
                WHERE t.owner = :schema
                ORDER BY t.table_name
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedTable(
                schema_name=r["schema_name"],
                table_name=r["table_name"],
                table_type="BASE TABLE",
                table_comment=r["table_comment"],
            )
            for r in rows
        ]

    def _fetch_columns(self, conn, schema_name: str) -> list[InspectedColumn]:
        # DATA_DEFAULT is LONG in older Oracle; omit it to keep SELECT portable.
        rows = conn.execute(
            text(
                """
                SELECT tc.owner AS schema_name,
                       tc.table_name,
                       tc.column_id AS ordinal_position,
                       tc.column_name,
                       tc.data_type,
                       CASE
                           WHEN tc.data_type IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'RAW')
                               THEN tc.data_length
                           ELSE NULL
                       END AS character_maximum_length,
                       tc.data_precision AS numeric_precision,
                       tc.data_scale AS numeric_scale,
                       tc.nullable,
                       cc.comments AS column_comment
                FROM all_tab_columns tc
                LEFT JOIN all_col_comments cc
                  ON cc.owner = tc.owner
                 AND cc.table_name = tc.table_name
                 AND cc.column_name = tc.column_name
                WHERE tc.owner = :schema
                ORDER BY tc.table_name, tc.column_id
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedColumn(
                schema_name=r["schema_name"],
                table_name=r["table_name"],
                ordinal_position=int(r["ordinal_position"] or 0),
                column_name=r["column_name"],
                data_type=r["data_type"] or "",
                character_maximum_length=(
                    int(r["character_maximum_length"])
                    if r["character_maximum_length"] is not None
                    else None
                ),
                numeric_precision=(
                    int(r["numeric_precision"]) if r["numeric_precision"] is not None else None
                ),
                numeric_scale=(
                    int(r["numeric_scale"]) if r["numeric_scale"] is not None else None
                ),
                is_nullable=str(r["nullable"]).upper() == "Y",
                default_value=None,
                column_comment=r["column_comment"],
            )
            for r in rows
        ]

    def _fetch_primary_keys(self, conn, schema_name: str) -> list[InspectedPrimaryKey]:
        rows = conn.execute(
            text(
                """
                SELECT c.owner AS schema_name,
                       c.table_name,
                       c.constraint_name,
                       cc.column_name,
                       cc.position AS ordinal_position
                FROM all_constraints c
                JOIN all_cons_columns cc
                  ON cc.owner = c.owner
                 AND cc.constraint_name = c.constraint_name
                 AND cc.table_name = c.table_name
                WHERE c.owner = :schema
                  AND c.constraint_type = 'P'
                ORDER BY c.table_name, cc.position
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedPrimaryKey(
                schema_name=r["schema_name"],
                table_name=r["table_name"],
                constraint_name=r["constraint_name"],
                column_name=r["column_name"],
                ordinal_position=int(r["ordinal_position"] or 0),
            )
            for r in rows
        ]

    def _fetch_unique_constraints(self, conn, schema_name: str) -> list[InspectedUniqueConstraint]:
        rows = conn.execute(
            text(
                """
                SELECT c.owner AS schema_name,
                       c.table_name,
                       c.constraint_name,
                       cc.column_name,
                       cc.position AS ordinal_position
                FROM all_constraints c
                JOIN all_cons_columns cc
                  ON cc.owner = c.owner
                 AND cc.constraint_name = c.constraint_name
                 AND cc.table_name = c.table_name
                WHERE c.owner = :schema
                  AND c.constraint_type = 'U'
                ORDER BY c.table_name, c.constraint_name, cc.position
                """
            ),
            {"schema": schema_name},
        ).mappings()
        return [
            InspectedUniqueConstraint(
                schema_name=r["schema_name"],
                table_name=r["table_name"],
                constraint_name=r["constraint_name"],
                column_name=r["column_name"],
                ordinal_position=int(r["ordinal_position"] or 0),
            )
            for r in rows
        ]

    def _fetch_foreign_keys(self, conn, schema_name: str) -> list[InspectedForeignKey]:
        rows = conn.execute(
            text(
                """
                SELECT c.constraint_name,
                       c.owner AS source_schema,
                       c.table_name AS source_table,
                       cc.column_name AS source_column,
                       c.r_owner AS target_schema,
                       rc.table_name AS target_table,
                       rcc.column_name AS target_column,
                       cc.position AS ordinal_position
                FROM all_constraints c
                JOIN all_cons_columns cc
                  ON cc.owner = c.owner
                 AND cc.constraint_name = c.constraint_name
                 AND cc.table_name = c.table_name
                JOIN all_constraints rc
                  ON rc.owner = c.r_owner
                 AND rc.constraint_name = c.r_constraint_name
                JOIN all_cons_columns rcc
                  ON rcc.owner = rc.owner
                 AND rcc.constraint_name = rc.constraint_name
                 AND rcc.table_name = rc.table_name
                 AND rcc.position = cc.position
                WHERE c.owner = :schema
                  AND c.constraint_type = 'R'
                ORDER BY c.constraint_name, cc.position
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
                    ordinal_position=int(r["ordinal_position"] or 0),
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
                SELECT i.table_owner AS schema_name,
                       i.table_name,
                       i.index_name,
                       i.uniqueness,
                       i.index_type,
                       ic.column_name,
                       ic.column_position AS ordinal_position
                FROM all_indexes i
                JOIN all_ind_columns ic
                  ON ic.index_owner = i.owner
                 AND ic.index_name = i.index_name
                WHERE i.table_owner = :schema
                  AND i.index_type NOT LIKE '%LOB%'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM all_constraints ac
                      WHERE ac.owner = i.table_owner
                        AND ac.table_name = i.table_name
                        AND ac.index_name = i.index_name
                        AND ac.constraint_type IN ('P', 'U')
                  )
                ORDER BY i.table_name, i.index_name, ic.column_position
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
                    "is_unique": str(r["uniqueness"]).upper() == "UNIQUE",
                    "index_method": r["index_type"],
                    "index_definition": None,
                    "columns": [],
                }
            grouped[key]["columns"].append(
                InspectedIndexColumn(
                    ordinal_position=int(r["ordinal_position"] or 0),
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
