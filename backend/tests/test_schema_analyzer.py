"""Step 2 Schema Analyzer / Catalog integration tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

REQUIRED_TABLES = {
    "tb_pt_mst",
    "tb_enc_hist",
    "tb_dgn_hist",
    "tb_dgn_cd_mst",
    "tb_ord_hdr",
    "tb_ord_dtl",
    "tb_lab_ord",
    "tb_lab_rst",
    "tb_lab_mst",
    "tb_lab_ref",
    "tb_med_ord",
    "tb_drug_mst",
    "tb_img_ord",
    "tb_img_rpt",
    "tb_img_mst",
    "tb_cln_doc",
    "tb_doc_type",
    "tb_dept_mst",
    "tb_provider",
    "tb_proc_hist",
    "tb_proc_mst",
    "tb_code_mst",
    "tb_ward_mst",
    "tb_adm_hist",
}


def _medical_url() -> str:
    host = os.getenv("MEDICAL_DB_HOST", "localhost")
    port = os.getenv("MEDICAL_DB_PORT", "5433")
    name = os.getenv("MEDICAL_DB_NAME", "medical_demo")
    user = os.getenv("MEDICAL_DB_USER", "medical_user")
    password = os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture(scope="module")
def medical_engine():
    engine = create_engine(_medical_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


@pytest.fixture(scope="module")
def catalog_engine():
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def analyzed(client):
    first = client.post("/api/v1/schema/analyze")
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/schema/analyze")
    assert second.status_code == 200, second.text
    return first.json(), second.json()


def test_inspector_detects_24_tables(medical_engine) -> None:
    from app.analyzers.postgres import PostgreSQLSchemaInspector

    snapshot = PostgreSQLSchemaInspector(medical_engine, "medical_demo").inspect("public")
    names = {t.table_name for t in snapshot.tables}
    assert len(snapshot.tables) == 24
    assert REQUIRED_TABLES.issubset(names)


def test_inspector_collects_columns_and_comments(medical_engine) -> None:
    from app.analyzers.postgres import PostgreSQLSchemaInspector

    snapshot = PostgreSQLSchemaInspector(medical_engine, "medical_demo").inspect("public")
    by_table: dict[str, list] = {}
    for col in snapshot.columns:
        by_table.setdefault(col.table_name, []).append(col)

    for table in ("tb_lab_rst", "tb_lab_mst", "tb_enc_hist"):
        cols = by_table[table]
        assert len(cols) >= 5
        assert any(c.column_comment for c in cols)

    lab_rst = {c.column_name: c for c in by_table["tb_lab_rst"]}
    assert "rst_val" in lab_rst
    assert "exm_cd" in lab_rst
    assert lab_rst["exm_cd"].column_comment


def test_inspector_collects_pk_fk_and_composite(medical_engine) -> None:
    from app.analyzers.postgres import PostgreSQLSchemaInspector

    snapshot = PostgreSQLSchemaInspector(medical_engine, "medical_demo").inspect("public")
    pk_cols = {(p.table_name, p.column_name, p.ordinal_position) for p in snapshot.primary_keys}
    assert ("tb_lab_rst", "lab_rst_id", 1) in pk_cols
    assert ("tb_code_mst", "cd_grp", 1) in pk_cols
    assert ("tb_code_mst", "cd_val", 2) in pk_cols

    fk_pairs = {(fk.source_table, fk.target_table) for fk in snapshot.foreign_keys}
    assert ("tb_lab_rst", "tb_lab_ord") in fk_pairs
    assert ("tb_lab_rst", "tb_lab_mst") in fk_pairs
    assert ("tb_enc_hist", "tb_pt_mst") in fk_pairs


def test_inspector_collects_indexes(medical_engine) -> None:
    from app.analyzers.postgres import PostgreSQLSchemaInspector

    snapshot = PostgreSQLSchemaInspector(medical_engine, "medical_demo").inspect("public")
    index_names = {ix.index_name for ix in snapshot.indexes}
    assert "ix_lab_rst_exm" in index_names
    assert "ix_enc_pt" in index_names
    assert len(snapshot.indexes) >= 20


def test_analyze_api_and_catalog_load(analyzed, catalog_engine) -> None:
    first, _second = analyzed
    assert first["status"] == "SUCCESS"
    assert first["tables"] == 24
    assert first["columns"] > 100
    assert first["relations"] > 20
    assert first["indexes"] > 10
    assert not first.get("error_message")

    with catalog_engine.connect() as conn:
        tables = conn.execute(text("SELECT COUNT(*) FROM catalog_table WHERE active")).scalar_one()
        columns = conn.execute(text("SELECT COUNT(*) FROM catalog_column WHERE active")).scalar_one()
        relations = conn.execute(text("SELECT COUNT(*) FROM catalog_relation WHERE active")).scalar_one()
        indexes = conn.execute(text("SELECT COUNT(*) FROM catalog_index WHERE active")).scalar_one()
        sources = conn.execute(
            text("SELECT COUNT(*) FROM catalog_source WHERE source_name='medical_demo'")
        ).scalar_one()
    assert tables == 24
    assert columns == first["columns"]
    assert relations == first["relations"]
    assert indexes == first["indexes"]
    assert sources == 1


def test_analyze_idempotency(analyzed, catalog_engine) -> None:
    first, second = analyzed
    assert first["status"] == second["status"] == "SUCCESS"
    assert first["tables"] == second["tables"]
    assert first["columns"] == second["columns"]
    assert first["relations"] == second["relations"]
    assert first["indexes"] == second["indexes"]
    assert first["run_id"] != second["run_id"]

    with catalog_engine.connect() as conn:
        table_rows = conn.execute(text("SELECT COUNT(*) FROM catalog_table")).scalar_one()
        column_rows = conn.execute(text("SELECT COUNT(*) FROM catalog_column")).scalar_one()
        relation_rows = conn.execute(text("SELECT COUNT(*) FROM catalog_relation")).scalar_one()
        run_rows = conn.execute(text("SELECT COUNT(*) FROM catalog_analysis_run")).scalar_one()
    assert table_rows == 24
    assert column_rows == first["columns"]
    assert relation_rows == first["relations"]
    assert run_rows >= 2


def test_fingerprint_stability(analyzed) -> None:
    first, second = analyzed
    assert first["schema_fingerprint"]
    assert first["schema_fingerprint"] == second["schema_fingerprint"]


def test_table_detail_api_for_lab_rst(client, analyzed) -> None:
    tables = client.get("/api/v1/schema/tables", params={"name": "tb_lab_rst"}).json()
    assert len(tables) == 1
    detail = client.get(f"/api/v1/schema/tables/{tables[0]['id']}").json()
    assert detail["table_name"] == "tb_lab_rst"
    assert detail["table_comment"]
    assert len(detail["columns"]) >= 8
    assert any(c["primary_key"] for c in detail["columns"])
    assert any(c["column_name"] == "exm_cd" for c in detail["columns"])
    targets = {r["target_table"] for r in detail["outbound_relations"]}
    assert "tb_lab_ord" in targets
    assert "tb_lab_mst" in targets
    assert len(detail["indexes"]) >= 1


def test_analysis_run_api(client, analyzed) -> None:
    _first, second = analyzed
    runs = client.get("/api/v1/schema/runs").json()
    assert len(runs) >= 2
    run = client.get(f"/api/v1/schema/runs/{second['run_id']}").json()
    assert run["status"] == "SUCCESS"
    assert run["table_count"] == 24
    assert run["id"] == second["run_id"]


def test_credentials_not_exposed(client, analyzed) -> None:
    first, _ = analyzed
    password = os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")
    catalog_password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    blob = str(first) + str(client.get("/api/v1/schema/runs").json())
    assert password not in blob
    assert catalog_password not in blob


def test_composite_pk_stored_with_ordinals(analyzed, catalog_engine) -> None:
    with catalog_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT kc.constraint_name, kc.constraint_type,
                       kcc.ordinal_position, c.column_name,
                       c.is_primary_key, c.is_unique
                FROM catalog_key_constraint kc
                JOIN catalog_table t ON t.id = kc.table_id
                JOIN catalog_key_constraint_column kcc ON kcc.constraint_id = kc.id
                JOIN catalog_column c ON c.id = kcc.column_id
                WHERE t.table_name = 'tb_code_mst'
                  AND kc.constraint_type = 'PRIMARY_KEY'
                  AND kc.active
                ORDER BY kcc.ordinal_position
                """
            )
        ).mappings().all()
    assert len(rows) == 2
    assert rows[0]["column_name"] == "cd_grp" and rows[0]["ordinal_position"] == 1
    assert rows[1]["column_name"] == "cd_val" and rows[1]["ordinal_position"] == 2
    # Composite PK members are PK columns but not individually unique.
    assert rows[0]["is_primary_key"] is True and rows[0]["is_unique"] is False
    assert rows[1]["is_primary_key"] is True and rows[1]["is_unique"] is False


def test_single_column_unique_flag(analyzed, catalog_engine) -> None:
    with catalog_engine.connect() as conn:
        lab_ord_unique = conn.execute(
            text(
                """
                SELECT c.is_unique, c.is_primary_key
                FROM catalog_column c
                JOIN catalog_table t ON t.id = c.table_id
                WHERE t.table_name = 'tb_lab_rst' AND c.column_name = 'lab_ord_id' AND c.active
                """
            )
        ).mappings().one()
        # Composite UNIQUE on tb_ord_dtl should not mark members as alone-unique.
        ord_dtl = conn.execute(
            text(
                """
                SELECT c.column_name, c.is_unique
                FROM catalog_column c
                JOIN catalog_table t ON t.id = c.table_id
                JOIN catalog_key_constraint kc ON kc.table_id = t.id
                JOIN catalog_key_constraint_column kcc ON kcc.constraint_id = kc.id AND kcc.column_id = c.id
                WHERE t.table_name = 'tb_ord_dtl'
                  AND kc.constraint_type = 'UNIQUE'
                  AND kc.active
                ORDER BY kcc.ordinal_position
                """
            )
        ).mappings().all()
    assert lab_ord_unique["is_unique"] is True
    assert lab_ord_unique["is_primary_key"] is False
    assert len(ord_dtl) >= 2
    assert all(row["is_unique"] is False for row in ord_dtl)


def test_key_constraint_idempotency(analyzed, catalog_engine) -> None:
    with catalog_engine.connect() as conn:
        key_rows = conn.execute(text("SELECT COUNT(*) FROM catalog_key_constraint")).scalar_one()
        key_col_rows = conn.execute(
            text("SELECT COUNT(*) FROM catalog_key_constraint_column")
        ).scalar_one()
        active_keys = conn.execute(
            text("SELECT COUNT(*) FROM catalog_key_constraint WHERE active")
        ).scalar_one()
    assert key_rows == active_keys
    assert key_rows > 0
    assert key_col_rows >= key_rows


def test_relation_natural_key_allows_duplicate_constraint_names() -> None:
    """Same FK constraint_name on different source tables must not collide."""
    from app.analyzers.base import (
        InspectedColumn,
        InspectedForeignKey,
        InspectedForeignKeyColumn,
        InspectedTable,
        SchemaSnapshot,
    )
    from app.db.catalog_bootstrap import ensure_catalog_schema
    from app.db.session import get_catalog_session_factory
    from app.models.catalog import CatalogRelation, CatalogSource, CatalogTable
    from app.services.catalog_writer import CatalogWriter
    from sqlalchemy import select

    ensure_catalog_schema()
    session = get_catalog_session_factory()()
    try:
        source = session.scalar(
            select(CatalogSource).where(CatalogSource.source_name == "fk_collision_fixture")
        )
        if source is None:
            source = CatalogSource(
                source_name="fk_collision_fixture",
                db_type="postgresql",
                host="localhost",
                port=5432,
                database_name="fixture",
                default_schema="public",
                enabled=True,
            )
            session.add(source)
            session.commit()
            session.refresh(source)

        def _col(table: str, name: str, ordinal: int = 1) -> InspectedColumn:
            return InspectedColumn(
                schema_name="public",
                table_name=table,
                ordinal_position=ordinal,
                column_name=name,
                data_type="bigint",
                character_maximum_length=None,
                numeric_precision=None,
                numeric_scale=None,
                is_nullable=False,
                default_value=None,
                column_comment=None,
            )

        snapshot = SchemaSnapshot(
            db_type="postgresql",
            database_name="fixture",
            schema_name="public",
            tables=[
                InspectedTable("public", "t_a", "BASE TABLE", None),
                InspectedTable("public", "t_b", "BASE TABLE", None),
                InspectedTable("public", "t_ref", "BASE TABLE", None),
            ],
            columns=[
                _col("t_a", "id"),
                _col("t_a", "ref_id", 2),
                _col("t_b", "id"),
                _col("t_b", "ref_id", 2),
                _col("t_ref", "id"),
            ],
            foreign_keys=[
                InspectedForeignKey(
                    schema_name="public",
                    constraint_name="fk_shared_name",
                    source_table="t_a",
                    target_schema="public",
                    target_table="t_ref",
                    columns=(InspectedForeignKeyColumn(1, "ref_id", "id"),),
                ),
                InspectedForeignKey(
                    schema_name="public",
                    constraint_name="fk_shared_name",
                    source_table="t_b",
                    target_schema="public",
                    target_table="t_ref",
                    columns=(InspectedForeignKeyColumn(1, "ref_id", "id"),),
                ),
            ],
        )
        writer = CatalogWriter(session)
        writer.upsert_snapshot(source_id=source.id, run_id=None, snapshot=snapshot)
        # Second upsert must remain idempotent (still 2 relations, not 4).
        writer.upsert_snapshot(source_id=source.id, run_id=None, snapshot=snapshot)
        session.commit()

        rels = session.scalars(
            select(CatalogRelation).where(
                CatalogRelation.source_id == source.id,
                CatalogRelation.constraint_name == "fk_shared_name",
                CatalogRelation.active.is_(True),
            )
        ).all()
        assert len(rels) == 2
        assert len({r.source_table_id for r in rels}) == 2

        tables = session.scalars(
            select(CatalogTable).where(CatalogTable.source_id == source.id, CatalogTable.active.is_(True))
        ).all()
        assert len(tables) == 3
    finally:
        session.close()
