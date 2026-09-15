"""Unit tests for Multi-DB schema inspectors (merge + Oracle/MySQL mocks)."""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

from app.analyzers.base import (
    InspectedColumn,
    InspectedForeignKey,
    InspectedForeignKeyColumn,
    InspectedIndex,
    InspectedIndexColumn,
    InspectedPrimaryKey,
    InspectedTable,
    InspectedUniqueConstraint,
    SchemaSnapshot,
    merge_snapshots,
)
from app.analyzers.mysql_family import MySQLFamilySchemaInspector
from app.analyzers.oracle import OracleSchemaInspector


def _col(
    schema: str,
    table: str,
    name: str,
    ordinal: int = 1,
    *,
    data_type: str = "bigint",
    comment: str | None = None,
) -> InspectedColumn:
    return InspectedColumn(
        schema_name=schema,
        table_name=table,
        ordinal_position=ordinal,
        column_name=name,
        data_type=data_type,
        character_maximum_length=None,
        numeric_precision=None,
        numeric_scale=None,
        is_nullable=False,
        default_value=None,
        column_comment=comment,
    )


def test_merge_snapshots_concatenates_metadata() -> None:
    a = SchemaSnapshot(
        db_type="postgresql",
        database_name="demo",
        schema_name="public",
        tables=[InspectedTable("public", "tb_a", "BASE TABLE", "A")],
        columns=[_col("public", "tb_a", "id")],
        primary_keys=[
            InspectedPrimaryKey("public", "tb_a", "pk_a", "id", 1),
        ],
        unique_constraints=[],
        foreign_keys=[],
        indexes=[],
    )
    b = SchemaSnapshot(
        db_type="postgresql",
        database_name="demo",
        schema_name="analytics",
        tables=[InspectedTable("analytics", "tb_b", "BASE TABLE", "B")],
        columns=[_col("analytics", "tb_b", "id")],
        primary_keys=[
            InspectedPrimaryKey("analytics", "tb_b", "pk_b", "id", 1),
        ],
        unique_constraints=[
            InspectedUniqueConstraint("analytics", "tb_b", "uq_b", "id", 1),
        ],
        foreign_keys=[
            InspectedForeignKey(
                schema_name="analytics",
                constraint_name="fk_b_a",
                source_table="tb_b",
                target_schema="public",
                target_table="tb_a",
                columns=(InspectedForeignKeyColumn(1, "id", "id"),),
            )
        ],
        indexes=[
            InspectedIndex(
                schema_name="analytics",
                table_name="tb_b",
                index_name="ix_b",
                is_unique=False,
                index_method="btree",
                index_definition=None,
                columns=(InspectedIndexColumn(1, "id"),),
            )
        ],
    )

    merged = merge_snapshots([a, b])
    assert merged.db_type == "postgresql"
    assert merged.database_name == "demo"
    assert merged.schema_name == "analytics,public"
    assert {t.table_name for t in merged.tables} == {"tb_a", "tb_b"}
    assert len(merged.columns) == 2
    assert len(merged.primary_keys) == 2
    assert len(merged.unique_constraints) == 1
    assert len(merged.foreign_keys) == 1
    assert len(merged.indexes) == 1


def test_merge_snapshots_requires_non_empty() -> None:
    with pytest.raises(ValueError, match="at least one"):
        merge_snapshots([])


def _mapping_rows(rows: list[dict]) -> MagicMock:
    result = MagicMock()
    result.mappings.return_value = rows
    return result


def test_oracle_inspector_normalizes_pk_uq_fk_index() -> None:
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False

    def execute_side_effect(statement, params=None):
        sql = str(statement).lower()
        if "from all_tables" in sql and "all_tab_comments" in sql:
            return _mapping_rows(
                [
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_PATIENT",
                        "table_comment": "환자",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_ORDER",
                        "table_comment": "오더",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_CODE",
                        "table_comment": "코드",
                    },
                ]
            )
        if "from all_tab_columns" in sql:
            return _mapping_rows(
                [
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_PATIENT",
                        "ordinal_position": 1,
                        "column_name": "PATIENT_ID",
                        "data_type": "NUMBER",
                        "character_maximum_length": None,
                        "numeric_precision": 19,
                        "numeric_scale": 0,
                        "nullable": "N",
                        "column_comment": "환자 ID",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_PATIENT",
                        "ordinal_position": 2,
                        "column_name": "PATIENT_NO",
                        "data_type": "VARCHAR2",
                        "character_maximum_length": 40,
                        "numeric_precision": None,
                        "numeric_scale": None,
                        "nullable": "N",
                        "column_comment": "환자번호",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_CODE",
                        "ordinal_position": 1,
                        "column_name": "CD_GRP",
                        "data_type": "VARCHAR2",
                        "character_maximum_length": 20,
                        "numeric_precision": None,
                        "numeric_scale": None,
                        "nullable": "N",
                        "column_comment": "그룹",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_CODE",
                        "ordinal_position": 2,
                        "column_name": "CD_VAL",
                        "data_type": "VARCHAR2",
                        "character_maximum_length": 40,
                        "numeric_precision": None,
                        "numeric_scale": None,
                        "nullable": "N",
                        "column_comment": "값",
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_ORDER",
                        "ordinal_position": 1,
                        "column_name": "ORDER_ID",
                        "data_type": "NUMBER",
                        "character_maximum_length": None,
                        "numeric_precision": 19,
                        "numeric_scale": 0,
                        "nullable": "N",
                        "column_comment": None,
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_ORDER",
                        "ordinal_position": 2,
                        "column_name": "PATIENT_ID",
                        "data_type": "NUMBER",
                        "character_maximum_length": None,
                        "numeric_precision": 19,
                        "numeric_scale": 0,
                        "nullable": "N",
                        "column_comment": None,
                    },
                ]
            )
        if "constraint_type = 'p'" in sql:
            return _mapping_rows(
                [
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_PATIENT",
                        "constraint_name": "PK_PATIENT",
                        "column_name": "PATIENT_ID",
                        "ordinal_position": 1,
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_CODE",
                        "constraint_name": "PK_CODE",
                        "column_name": "CD_GRP",
                        "ordinal_position": 1,
                    },
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_CODE",
                        "constraint_name": "PK_CODE",
                        "column_name": "CD_VAL",
                        "ordinal_position": 2,
                    },
                ]
            )
        if "constraint_type = 'u'" in sql:
            return _mapping_rows(
                [
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_PATIENT",
                        "constraint_name": "UQ_PATIENT_NO",
                        "column_name": "PATIENT_NO",
                        "ordinal_position": 1,
                    }
                ]
            )
        if "constraint_type = 'r'" in sql:
            return _mapping_rows(
                [
                    {
                        "constraint_name": "FK_ORDER_PATIENT",
                        "source_schema": "DEMO",
                        "source_table": "TB_SHARED_ORDER",
                        "source_column": "PATIENT_ID",
                        "target_schema": "DEMO",
                        "target_table": "TB_SHARED_PATIENT",
                        "target_column": "PATIENT_ID",
                        "ordinal_position": 1,
                    },
                    {
                        "constraint_name": "FK_CODE_MAP",
                        "source_schema": "DEMO",
                        "source_table": "TB_SHARED_CODE_MAP",
                        "source_column": "CD_GRP",
                        "target_schema": "DEMO",
                        "target_table": "TB_SHARED_CODE",
                        "target_column": "CD_GRP",
                        "ordinal_position": 1,
                    },
                    {
                        "constraint_name": "FK_CODE_MAP",
                        "source_schema": "DEMO",
                        "source_table": "TB_SHARED_CODE_MAP",
                        "source_column": "CD_VAL",
                        "target_schema": "DEMO",
                        "target_table": "TB_SHARED_CODE",
                        "target_column": "CD_VAL",
                        "ordinal_position": 2,
                    },
                ]
            )
        if "from all_indexes" in sql:
            return _mapping_rows(
                [
                    {
                        "schema_name": "DEMO",
                        "table_name": "TB_SHARED_ORDER",
                        "index_name": "IX_ORDER_PATIENT",
                        "uniqueness": "NONUNIQUE",
                        "index_type": "NORMAL",
                        "column_name": "PATIENT_ID",
                        "ordinal_position": 1,
                    }
                ]
            )
        return _mapping_rows([])

    conn.execute.side_effect = execute_side_effect

    snap = OracleSchemaInspector(engine, "ORCL").inspect("DEMO")
    assert snap.db_type == "oracle"
    assert {t.table_name for t in snap.tables} >= {
        "TB_SHARED_PATIENT",
        "TB_SHARED_ORDER",
        "TB_SHARED_CODE",
    }

    pk = {(p.table_name, p.column_name, p.ordinal_position) for p in snap.primary_keys}
    assert ("TB_SHARED_PATIENT", "PATIENT_ID", 1) in pk
    assert ("TB_SHARED_CODE", "CD_GRP", 1) in pk
    assert ("TB_SHARED_CODE", "CD_VAL", 2) in pk

    uq = {(u.table_name, u.column_name) for u in snap.unique_constraints}
    assert ("TB_SHARED_PATIENT", "PATIENT_NO") in uq

    fk_by_name = {fk.constraint_name: fk for fk in snap.foreign_keys}
    assert "FK_ORDER_PATIENT" in fk_by_name
    composite = fk_by_name["FK_CODE_MAP"]
    assert len(composite.columns) == 2
    assert [c.source_column for c in composite.columns] == ["CD_GRP", "CD_VAL"]

    assert any(ix.index_name == "IX_ORDER_PATIENT" for ix in snap.indexes)

    patient_cols = [c for c in snap.columns if c.table_name == "TB_SHARED_PATIENT"]
    assert any(c.column_comment for c in patient_cols)


def test_mysql_family_normalizes_pk_composite_fk_and_index() -> None:
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False

    def execute_side_effect(statement, params=None):
        sql = str(statement).lower()
        if "from information_schema.tables" in sql:
            return _mapping_rows(
                [
                    {
                        "TABLE_NAME": "tb_shared_patient",
                        "TABLE_TYPE": "BASE TABLE",
                        "TABLE_COMMENT": "공유 환자 마스터",
                    },
                    {
                        "TABLE_NAME": "tb_shared_order",
                        "TABLE_TYPE": "BASE TABLE",
                        "TABLE_COMMENT": "공유 오더",
                    },
                    {
                        "TABLE_NAME": "tb_shared_code",
                        "TABLE_TYPE": "BASE TABLE",
                        "TABLE_COMMENT": "공유 코드 (복합 PK)",
                    },
                    {
                        "TABLE_NAME": "tb_shared_code_map",
                        "TABLE_TYPE": "BASE TABLE",
                        "TABLE_COMMENT": "코드 매핑 (복합 FK)",
                    },
                ]
            )
        if "from information_schema.columns" in sql:
            return _mapping_rows(
                [
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_patient",
                        "ORDINAL_POSITION": 1,
                        "COLUMN_NAME": "patient_id",
                        "DATA_TYPE": "bigint",
                        "CHARACTER_MAXIMUM_LENGTH": None,
                        "NUMERIC_PRECISION": 19,
                        "NUMERIC_SCALE": 0,
                        "IS_NULLABLE": "NO",
                        "COLUMN_DEFAULT": None,
                        "COLUMN_COMMENT": "환자 ID",
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_patient",
                        "ORDINAL_POSITION": 2,
                        "COLUMN_NAME": "patient_no",
                        "DATA_TYPE": "varchar",
                        "CHARACTER_MAXIMUM_LENGTH": 40,
                        "NUMERIC_PRECISION": None,
                        "NUMERIC_SCALE": None,
                        "IS_NULLABLE": "NO",
                        "COLUMN_DEFAULT": None,
                        "COLUMN_COMMENT": "환자번호",
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_code",
                        "ORDINAL_POSITION": 1,
                        "COLUMN_NAME": "cd_grp",
                        "DATA_TYPE": "varchar",
                        "CHARACTER_MAXIMUM_LENGTH": 20,
                        "NUMERIC_PRECISION": None,
                        "NUMERIC_SCALE": None,
                        "IS_NULLABLE": "NO",
                        "COLUMN_DEFAULT": None,
                        "COLUMN_COMMENT": "코드그룹",
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_code",
                        "ORDINAL_POSITION": 2,
                        "COLUMN_NAME": "cd_val",
                        "DATA_TYPE": "varchar",
                        "CHARACTER_MAXIMUM_LENGTH": 40,
                        "NUMERIC_PRECISION": None,
                        "NUMERIC_SCALE": None,
                        "IS_NULLABLE": "NO",
                        "COLUMN_DEFAULT": None,
                        "COLUMN_COMMENT": "코드값",
                    },
                ]
            )
        if "constraint_type = 'primary key'" in sql:
            return _mapping_rows(
                [
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_patient",
                        "CONSTRAINT_NAME": "PRIMARY",
                        "COLUMN_NAME": "patient_id",
                        "ORDINAL_POSITION": 1,
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_code",
                        "CONSTRAINT_NAME": "PRIMARY",
                        "COLUMN_NAME": "cd_grp",
                        "ORDINAL_POSITION": 1,
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_code",
                        "CONSTRAINT_NAME": "PRIMARY",
                        "COLUMN_NAME": "cd_val",
                        "ORDINAL_POSITION": 2,
                    },
                ]
            )
        if "constraint_type = 'unique'" in sql:
            return _mapping_rows(
                [
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_patient",
                        "CONSTRAINT_NAME": "uq_shared_patient_no",
                        "COLUMN_NAME": "patient_no",
                        "ORDINAL_POSITION": 1,
                    }
                ]
            )
        if "constraint_type = 'foreign key'" in sql:
            return _mapping_rows(
                [
                    {
                        "CONSTRAINT_NAME": "fk_shared_order_patient",
                        "source_schema": "iso_demo",
                        "source_table": "tb_shared_order",
                        "source_column": "patient_id",
                        "target_schema": "iso_demo",
                        "target_table": "tb_shared_patient",
                        "target_column": "patient_id",
                        "ordinal_position": 1,
                    },
                    {
                        "CONSTRAINT_NAME": "fk_shared_code_map",
                        "source_schema": "iso_demo",
                        "source_table": "tb_shared_code_map",
                        "source_column": "cd_grp",
                        "target_schema": "iso_demo",
                        "target_table": "tb_shared_code",
                        "target_column": "cd_grp",
                        "ordinal_position": 1,
                    },
                    {
                        "CONSTRAINT_NAME": "fk_shared_code_map",
                        "source_schema": "iso_demo",
                        "source_table": "tb_shared_code_map",
                        "source_column": "cd_val",
                        "target_schema": "iso_demo",
                        "target_table": "tb_shared_code",
                        "target_column": "cd_val",
                        "ordinal_position": 2,
                    },
                ]
            )
        if "from information_schema.statistics" in sql:
            return _mapping_rows(
                [
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_order",
                        "INDEX_NAME": "ix_shared_order_patient",
                        "NON_UNIQUE": 1,
                        "INDEX_TYPE": "BTREE",
                        "COLUMN_NAME": "patient_id",
                        "SEQ_IN_INDEX": 1,
                    },
                    {
                        "TABLE_SCHEMA": "iso_demo",
                        "TABLE_NAME": "tb_shared_patient",
                        "INDEX_NAME": "uq_shared_patient_no",
                        "NON_UNIQUE": 0,
                        "INDEX_TYPE": "BTREE",
                        "COLUMN_NAME": "patient_no",
                        "SEQ_IN_INDEX": 1,
                    },
                ]
            )
        return _mapping_rows([])

    conn.execute.side_effect = execute_side_effect

    for db_type in ("mysql", "mariadb"):
        snap = MySQLFamilySchemaInspector(engine, "iso_demo", db_type=db_type).inspect(
            "iso_demo"
        )
        assert snap.db_type == db_type
        names = {t.table_name for t in snap.tables}
        assert {
            "tb_shared_patient",
            "tb_shared_order",
            "tb_shared_code",
            "tb_shared_code_map",
        }.issubset(names)
        assert any(t.table_comment for t in snap.tables)

        pk = {(p.table_name, p.column_name, p.ordinal_position) for p in snap.primary_keys}
        assert ("tb_shared_patient", "patient_id", 1) in pk
        assert ("tb_shared_code", "cd_grp", 1) in pk
        assert ("tb_shared_code", "cd_val", 2) in pk

        assert any(u.constraint_name == "uq_shared_patient_no" for u in snap.unique_constraints)

        fk_map = {fk.constraint_name: fk for fk in snap.foreign_keys}
        assert "fk_shared_order_patient" in fk_map
        composite = fk_map["fk_shared_code_map"]
        assert len(composite.columns) == 2
        assert [c.source_column for c in composite.columns] == ["cd_grp", "cd_val"]
        assert composite.target_table == "tb_shared_code"

        ix_names = {ix.index_name for ix in snap.indexes}
        assert "ix_shared_order_patient" in ix_names


def _live_mysql_url(prefix: str) -> str | None:
    host = os.getenv(f"{prefix}_HOST")
    if not host:
        return None
    port = os.getenv(f"{prefix}_PORT", "3306")
    user = os.getenv(f"{prefix}_USER", "test")
    password = os.getenv(f"{prefix}_PASSWORD", "test")
    database = os.getenv(f"{prefix}_DATABASE", "iso_demo")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


@pytest.mark.skipif(not os.getenv("MYSQL_TEST_HOST"), reason="MYSQL_TEST_HOST not set")
def test_mysql_live_smoke_inspect() -> None:
    from sqlalchemy import create_engine, text

    from app.analyzers.mysql import MySQLSchemaInspector

    url = _live_mysql_url("MYSQL_TEST")
    assert url
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    inspector = MySQLSchemaInspector(engine, "iso_demo")
    schemas = inspector.list_schemas()
    assert "iso_demo" in schemas
    snap = inspector.inspect("iso_demo")
    assert "tb_shared_patient" in {t.table_name for t in snap.tables}
    assert any(pk.table_name == "tb_shared_code" for pk in snap.primary_keys)


@pytest.mark.skipif(not os.getenv("MARIADB_TEST_HOST"), reason="MARIADB_TEST_HOST not set")
def test_mariadb_live_smoke_inspect() -> None:
    from sqlalchemy import create_engine, text

    from app.analyzers.mariadb import MariaDBSchemaInspector

    url = _live_mysql_url("MARIADB_TEST")
    assert url
    engine = create_engine(url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    inspector = MariaDBSchemaInspector(engine, "iso_demo")
    schemas = inspector.list_schemas()
    assert "iso_demo" in schemas
    snap = inspector.inspect("iso_demo")
    assert "tb_shared_order" in {t.table_name for t in snap.tables}
    assert any(fk.constraint_name == "fk_shared_code_map" for fk in snap.foreign_keys)
