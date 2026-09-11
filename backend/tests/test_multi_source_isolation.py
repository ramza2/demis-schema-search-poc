"""Multi-source catalog isolation: identical table names must not cross sources."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.analyzers.base import (
    InspectedColumn,
    InspectedForeignKey,
    InspectedForeignKeyColumn,
    InspectedPrimaryKey,
    InspectedTable,
    SchemaSnapshot,
)
from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogSearchDocument,
    CatalogSource,
    CatalogTable,
)
from app.services.catalog_writer import CatalogWriter
from app.services.fingerprint import fingerprint
from app.services.search.keyword import keyword_search
from app.services.search.relation_expander import expand_relations
from app.services.search_document_builder import table_document_key


def _catalog_env() -> None:
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))


def _col(table: str, name: str, ordinal: int = 1, comment: str | None = None) -> InspectedColumn:
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
        column_comment=comment,
    )


def _snapshot(*, patient_comment: str, order_comment: str) -> SchemaSnapshot:
    return SchemaSnapshot(
        db_type="postgresql",
        database_name="iso_fixture",
        schema_name="public",
        tables=[
            InspectedTable("public", "tb_shared_patient", "BASE TABLE", patient_comment),
            InspectedTable("public", "tb_shared_order", "BASE TABLE", order_comment),
        ],
        columns=[
            _col("tb_shared_patient", "patient_id", 1, "patient pk"),
            _col("tb_shared_order", "order_id", 1, "order pk"),
            _col("tb_shared_order", "patient_id", 2, "patient fk"),
        ],
        primary_keys=[
            InspectedPrimaryKey("public", "tb_shared_patient", "pk_patient", "patient_id", 1),
            InspectedPrimaryKey("public", "tb_shared_order", "pk_order", "order_id", 1),
        ],
        unique_constraints=[],
        foreign_keys=[
            InspectedForeignKey(
                schema_name="public",
                constraint_name="fk_shared_order_patient",
                source_table="tb_shared_order",
                target_schema="public",
                target_table="tb_shared_patient",
                columns=(InspectedForeignKeyColumn(1, "patient_id", "patient_id"),),
            )
        ],
        indexes=[],
    )


def _delete_source(source_id: int) -> None:
    """Best-effort cleanup of a fixture CatalogSource and dependents."""
    session = get_catalog_session_factory()()
    try:
        session.execute(
            text("UPDATE catalog_table SET last_run_id = NULL WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("UPDATE catalog_relation SET last_run_id = NULL WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_search_document WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_relation WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_table WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_analysis_run WHERE source_id = :sid"),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_source WHERE id = :sid"),
            {"sid": source_id},
        )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


@pytest.fixture()
def client():
    _catalog_env()
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.db.catalog_bootstrap import ensure_catalog_schema
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    ensure_catalog_schema()

    with TestClient(create_app()) as test_client:
        yield test_client


def test_multi_source_table_and_search_isolation(client) -> None:
    suffix = uuid.uuid4().hex[:8]
    name_a = f"iso_source_a_{suffix}"
    name_b = f"iso_source_b_{suffix}"
    source_ids: list[int] = []

    try:
        # --- setup (close session before TestClient HTTP calls) ---
        session = get_catalog_session_factory()()
        try:
            source_a = CatalogSource(
                source_name=name_a,
                db_type="postgresql",
                host="localhost",
                port=5432,
                database_name="iso_a",
                default_schema="public",
                username="u_a",
                enabled=True,
            )
            source_b = CatalogSource(
                source_name=name_b,
                db_type="postgresql",
                host="localhost",
                port=5432,
                database_name="iso_b",
                default_schema="public",
                username="u_b",
                enabled=True,
            )
            session.add_all([source_a, source_b])
            session.commit()
            session.refresh(source_a)
            session.refresh(source_b)
            source_ids = [int(source_a.id), int(source_b.id)]

            writer = CatalogWriter(session)
            writer.upsert_snapshot(
                source_id=source_a.id,
                run_id=None,
                snapshot=_snapshot(
                    patient_comment="SOURCE_A_PATIENT_MARKER",
                    order_comment="SOURCE_A_ORDER_MARKER",
                ),
            )
            writer.upsert_snapshot(
                source_id=source_b.id,
                run_id=None,
                snapshot=_snapshot(
                    patient_comment="SOURCE_B_PATIENT_MARKER",
                    order_comment="SOURCE_B_ORDER_MARKER",
                ),
            )
            session.commit()

            tables_a = session.scalars(
                select(CatalogTable).where(
                    CatalogTable.source_id == source_a.id,
                    CatalogTable.table_name == "tb_shared_patient",
                    CatalogTable.active.is_(True),
                )
            ).all()
            tables_b = session.scalars(
                select(CatalogTable).where(
                    CatalogTable.source_id == source_b.id,
                    CatalogTable.table_name == "tb_shared_patient",
                    CatalogTable.active.is_(True),
                )
            ).all()
            assert len(tables_a) == 1
            assert len(tables_b) == 1
            assert tables_a[0].table_comment == "SOURCE_A_PATIENT_MARKER"
            assert tables_b[0].table_comment == "SOURCE_B_PATIENT_MARKER"
            assert tables_a[0].id != tables_b[0].id
            table_a_id = int(tables_a[0].id)
            table_b_id = int(tables_b[0].id)
            source_a_id = int(source_a.id)
            source_b_id = int(source_b.id)

            for sid, marker, table_id in (
                (source_a_id, "ALPHA_ONLY_TOKEN_XYZ", table_a_id),
                (source_b_id, "BETA_ONLY_TOKEN_XYZ", table_b_id),
            ):
                key = table_document_key(sid, "public", "tb_shared_patient")
                text_value = f"tb_shared_patient {marker}"
                session.add(
                    CatalogSearchDocument(
                        source_id=sid,
                        object_type="TABLE",
                        table_id=table_id,
                        column_id=None,
                        document_key=key,
                        searchable_text=text_value,
                        source_fingerprint=fingerprint({"t": marker}),
                        document_fingerprint=fingerprint({"k": key, "t": text_value}),
                        builder_version="test",
                        active=True,
                    )
                )
            session.commit()
        finally:
            session.close()

        # --- HTTP API (no open ORM session held) ---
        resp_a = client.get(f"/api/v1/schema/tables?source_id={source_a_id}")
        resp_b = client.get(f"/api/v1/schema/tables?source_id={source_b_id}")
        assert resp_a.status_code == 200, resp_a.text
        assert resp_b.status_code == 200, resp_b.text
        comments_a = {
            row["table_name"]: row["table_comment"]
            for row in resp_a.json()
            if row["table_name"].startswith("tb_shared_")
        }
        comments_b = {
            row["table_name"]: row["table_comment"]
            for row in resp_b.json()
            if row["table_name"].startswith("tb_shared_")
        }
        assert comments_a["tb_shared_patient"] == "SOURCE_A_PATIENT_MARKER"
        assert comments_b["tb_shared_patient"] == "SOURCE_B_PATIENT_MARKER"
        assert "SOURCE_B_PATIENT_MARKER" not in comments_a.values()
        assert "SOURCE_A_PATIENT_MARKER" not in comments_b.values()

        # --- keyword + relation isolation ---
        session = get_catalog_session_factory()()
        try:
            hits_a, _ = keyword_search(
                session,
                original_query="ALPHA_ONLY_TOKEN_XYZ",
                expanded_query="ALPHA_ONLY_TOKEN_XYZ",
                original_terms=["ALPHA_ONLY_TOKEN_XYZ"],
                expanded_terms=[],
                limit=20,
                source_id=source_a_id,
            )
            hits_cross, _ = keyword_search(
                session,
                original_query="BETA_ONLY_TOKEN_XYZ",
                expanded_query="BETA_ONLY_TOKEN_XYZ",
                original_terms=["BETA_ONLY_TOKEN_XYZ"],
                expanded_terms=[],
                limit=20,
                source_id=source_a_id,
            )
            assert any("ALPHA_ONLY_TOKEN_XYZ" in h.searchable_text for h in hits_a)
            assert not any("BETA_ONLY_TOKEN_XYZ" in h.searchable_text for h in hits_a)
            assert hits_cross == []

            hits_b_ok, _ = keyword_search(
                session,
                original_query="BETA_ONLY_TOKEN_XYZ",
                expanded_query="BETA_ONLY_TOKEN_XYZ",
                original_terms=["BETA_ONLY_TOKEN_XYZ"],
                expanded_terms=[],
                limit=20,
                source_id=source_b_id,
            )
            assert any("BETA_ONLY_TOKEN_XYZ" in h.searchable_text for h in hits_b_ok)
            assert not any("ALPHA_ONLY_TOKEN_XYZ" in h.searchable_text for h in hits_b_ok)

            related_a = expand_relations(
                session,
                seed_table_names=["tb_shared_order"],
                max_hops=1,
                source_id=source_a_id,
            )
            related_b = expand_relations(
                session,
                seed_table_names=["tb_shared_order"],
                max_hops=1,
                source_id=source_b_id,
            )
            assert any(r.table_name == "tb_shared_patient" for r in related_a)
            assert any(r.table_name == "tb_shared_patient" for r in related_b)

            patient_ids_a = {
                t.id
                for t in session.scalars(
                    select(CatalogTable).where(CatalogTable.source_id == source_a_id)
                ).all()
            }
            for hit in related_a:
                table = session.scalar(
                    select(CatalogTable).where(
                        CatalogTable.schema_name == hit.schema_name,
                        CatalogTable.table_name == hit.table_name,
                        CatalogTable.source_id == source_a_id,
                    )
                )
                assert table is not None
                assert table.id in patient_ids_a
        finally:
            session.close()
    finally:
        for sid in source_ids:
            try:
                _delete_source(sid)
            except Exception:  # noqa: BLE001
                pass
