"""Focused tests for deterministic physical schema snapshot comparison."""

from __future__ import annotations

from app.services.schema_diff_service import compare_snapshot_payloads


def _base_payload() -> dict:
    return {
        "snapshot_version": "1.0",
        "tables": [
            {"schema": "DEMIS_OWNER", "name": "TB_MAIN", "table_type": "BASE TABLE", "comment": "old"},
            {"schema": "DEMIS_OWNER", "name": "TB_REMOVED", "table_type": "BASE TABLE", "comment": None},
        ],
        "columns": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "ID",
                "ordinal": 1,
                "data_type": "NUMBER",
                "char_length": None,
                "numeric_precision": 18,
                "numeric_scale": 0,
                "nullable": False,
                "default": None,
                "comment": "identifier",
            },
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "NAME",
                "ordinal": 2,
                "data_type": "VARCHAR2",
                "char_length": 50,
                "numeric_precision": None,
                "numeric_scale": None,
                "nullable": True,
                "default": None,
                "comment": None,
            },
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_REMOVED",
                "name": "X",
                "ordinal": 1,
                "data_type": "NUMBER",
                "char_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
                "nullable": True,
                "default": None,
                "comment": None,
            },
        ],
        "key_constraints": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "PK_TB_MAIN",
                "constraint_type": "PRIMARY_KEY",
                "columns": ["ID"],
            }
        ],
        "foreign_keys": [
            {
                "source_schema": "DEMIS_OWNER",
                "source_table": "TB_MAIN",
                "name": "FK_MAIN_PARENT",
                "target_schema": "DEMIS_OWNER",
                "target_table": "TB_PARENT",
                "mappings": [{"source": "ID", "target": "ID"}],
            }
        ],
        "indexes": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "IX_MAIN_NAME",
                "unique": False,
                "method": "NORMAL",
                "definition": None,
                "columns": ["NAME"],
            }
        ],
    }


def _target_payload() -> dict:
    return {
        "snapshot_version": "1.0",
        "tables": [
            {"schema": "DEMIS_OWNER", "name": "TB_MAIN", "table_type": "BASE TABLE", "comment": "new"},
            {"schema": "DEMIS_OWNER", "name": "TB_ADDED", "table_type": "BASE TABLE", "comment": None},
        ],
        "columns": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "ID",
                "ordinal": 1,
                "data_type": "NUMBER",
                "char_length": None,
                "numeric_precision": 18,
                "numeric_scale": 0,
                "nullable": False,
                "default": None,
                "comment": "identifier",
            },
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "NAME",
                "ordinal": 2,
                "data_type": "VARCHAR2",
                "char_length": 100,
                "numeric_precision": None,
                "numeric_scale": None,
                "nullable": True,
                "default": None,
                "comment": None,
            },
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "NEW_COL",
                "ordinal": 3,
                "data_type": "DATE",
                "char_length": None,
                "numeric_precision": None,
                "numeric_scale": None,
                "nullable": True,
                "default": None,
                "comment": None,
            },
        ],
        "key_constraints": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "PK_TB_MAIN",
                "constraint_type": "PRIMARY_KEY",
                "columns": ["ID"],
            },
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "UQ_TB_MAIN_NAME",
                "constraint_type": "UNIQUE",
                "columns": ["NAME"],
            },
        ],
        "foreign_keys": [
            {
                "source_schema": "DEMIS_OWNER",
                "source_table": "TB_MAIN",
                "name": "FK_MAIN_PARENT",
                "target_schema": "DEMIS_OWNER",
                "target_table": "TB_PARENT_V2",
                "mappings": [{"source": "ID", "target": "ID"}],
            }
        ],
        "indexes": [
            {
                "schema": "DEMIS_OWNER",
                "table": "TB_MAIN",
                "name": "IX_MAIN_NEW",
                "unique": False,
                "method": "NORMAL",
                "definition": None,
                "columns": ["NEW_COL"],
            }
        ],
    }


def test_compare_snapshot_payloads_reports_added_removed_changed() -> None:
    summary, changes = compare_snapshot_payloads(_base_payload(), _target_payload())

    assert summary.tables.added == 1
    assert summary.tables.removed == 1
    assert summary.tables.changed == 1
    assert summary.columns.added == 1
    assert summary.columns.removed == 1
    assert summary.columns.changed == 1
    assert summary.key_constraints.added == 1
    assert summary.key_constraints.removed == 0
    assert summary.key_constraints.changed == 0
    assert summary.foreign_keys.changed == 1
    assert summary.indexes.added == 1
    assert summary.indexes.removed == 1
    assert summary.indexes.changed == 0
    assert summary.total_changes == 10

    table_change = next(
        item
        for item in changes
        if item.object_type == "TABLE"
        and item.change_type == "CHANGED"
        and item.object_key == "DEMIS_OWNER.TB_MAIN"
    )
    assert table_change.changed_fields == ["comment"]

    column_change = next(
        item
        for item in changes
        if item.object_type == "COLUMN"
        and item.change_type == "CHANGED"
        and item.object_key == "DEMIS_OWNER.TB_MAIN.NAME"
    )
    assert column_change.changed_fields == ["char_length"]

    fk_change = next(
        item
        for item in changes
        if item.object_type == "FOREIGN_KEY"
        and item.change_type == "CHANGED"
    )
    assert "target_table" in fk_change.changed_fields


def test_compare_snapshot_payloads_is_order_independent_for_entities() -> None:
    base = _base_payload()
    target = _base_payload()
    target["tables"] = list(reversed(target["tables"]))
    target["columns"] = list(reversed(target["columns"]))
    target["key_constraints"] = list(reversed(target["key_constraints"]))

    summary, changes = compare_snapshot_payloads(base, target)

    assert summary.total_changes == 0
    assert changes == []


def test_constraint_column_order_is_a_physical_change() -> None:
    base = _base_payload()
    target = _base_payload()
    base["key_constraints"] = [
        {
            "schema": "DEMIS_OWNER",
            "table": "TB_MAIN",
            "name": "PK_TB_MAIN",
            "constraint_type": "PRIMARY_KEY",
            "columns": ["ID", "NAME"],
        }
    ]
    target["key_constraints"] = [
        {
            "schema": "DEMIS_OWNER",
            "table": "TB_MAIN",
            "name": "PK_TB_MAIN",
            "constraint_type": "PRIMARY_KEY",
            "columns": ["NAME", "ID"],
        }
    ]

    summary, changes = compare_snapshot_payloads(base, target)

    assert summary.key_constraints.changed == 1
    assert summary.total_changes == 1
    assert changes[0].changed_fields == ["columns"]
