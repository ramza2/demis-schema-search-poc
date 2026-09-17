"""Integration coverage for the source-scoped ERD graph API."""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db.session import get_catalog_session_factory
from app.models.catalog import (
    CatalogColumn,
    CatalogRelation,
    CatalogRelationColumn,
    CatalogSource,
    CatalogTable,
)
from app.models.catalog_category import CatalogCategory, CatalogTableCategory


def _catalog_env() -> None:
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))


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


def _fp(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _create_fixture() -> int:
    suffix = uuid.uuid4().hex[:8]
    session = get_catalog_session_factory()()
    try:
        source = CatalogSource(
            source_name=f"erd_source_{suffix}",
            db_type="oracle",
            host="SECRET_ERD_HOST",
            port=1521,
            database_name="FREEPDB1",
            default_schema="DEMIS_OWNER",
            enabled=True,
        )
        session.add(source)
        session.flush()

        patient = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name="TB_PT_MST",
            table_type="BASE TABLE",
            table_comment="환자 기본정보",
            object_fingerprint=_fp("patient" + suffix),
            active=True,
        )
        encounter = CatalogTable(
            source_id=source.id,
            schema_name="DEMIS_OWNER",
            table_name="TB_ENC_HIST",
            table_type="BASE TABLE",
            table_comment="환자 진료이력",
            object_fingerprint=_fp("encounter" + suffix),
            active=True,
        )
        session.add_all([patient, encounter])
        session.flush()

        patient_id = CatalogColumn(
            table_id=patient.id,
            ordinal_position=1,
            column_name="PT_ID",
            data_type="NUMBER",
            is_nullable=False,
            is_primary_key=True,
            is_unique=True,
            object_fingerprint=_fp("patient_id" + suffix),
            active=True,
        )
        encounter_patient_id = CatalogColumn(
            table_id=encounter.id,
            ordinal_position=1,
            column_name="PT_ID",
            data_type="NUMBER",
            is_nullable=False,
            is_primary_key=False,
            is_unique=False,
            object_fingerprint=_fp("encounter_patient_id" + suffix),
            active=True,
        )
        session.add_all([patient_id, encounter_patient_id])
        session.flush()

        relation = CatalogRelation(
            source_id=source.id,
            constraint_name="FK_ENC_PT",
            source_table_id=encounter.id,
            target_table_id=patient.id,
            relation_type="FOREIGN_KEY",
            object_fingerprint=_fp("relation" + suffix),
            active=True,
        )
        session.add(relation)
        session.flush()
        session.add(
            CatalogRelationColumn(
                relation_id=relation.id,
                ordinal_position=1,
                source_column_id=encounter_patient_id.id,
                target_column_id=patient_id.id,
            )
        )

        category = CatalogCategory(
            source_id=source.id,
            category_key="patient",
            category_name="환자",
            description="환자 관련",
            sort_order=10,
            active=True,
        )
        session.add(category)
        session.flush()
        session.add(
            CatalogTableCategory(
                table_id=patient.id,
                category_id=category.id,
                is_primary=True,
                assignment_source="MANUAL",
                confidence=None,
            )
        )
        session.commit()
        return int(source.id)
    finally:
        session.close()


def _cleanup(source_id: int) -> None:
    session = get_catalog_session_factory()()
    try:
        session.execute(
            text(
                "DELETE FROM catalog_table_category WHERE table_id IN "
                "(SELECT id FROM catalog_table WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        )
        session.execute(text("DELETE FROM catalog_category WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_relation WHERE source_id = :sid"), {"sid": source_id})
        session.execute(
            text(
                "DELETE FROM catalog_column WHERE table_id IN "
                "(SELECT id FROM catalog_table WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        )
        session.execute(text("DELETE FROM catalog_table WHERE source_id = :sid"), {"sid": source_id})
        session.execute(text("DELETE FROM catalog_source WHERE id = :sid"), {"sid": source_id})
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
        raise
    finally:
        session.close()


def test_erd_graph_returns_nodes_edges_categories_without_connection_secret(client: TestClient) -> None:
    source_id = _create_fixture()
    try:
        response = client.get("/api/v1/schema/erd", params={"source_id": source_id})
        assert response.status_code == 200, response.text
        data = response.json()

        assert data["counts"] == {"nodes": 2, "edges": 1, "categories": 1}
        assert data["source"]["source_name"].startswith("erd_source_")
        assert "host" not in data["source"]
        assert "SECRET_ERD_HOST" not in response.text

        node_by_name = {node["table_name"]: node for node in data["nodes"]}
        assert node_by_name["TB_PT_MST"]["categories"][0]["name"] == "환자"
        assert node_by_name["TB_PT_MST"]["categories"][0]["assignment_source"] == "MANUAL"

        edge = data["edges"][0]
        assert edge["constraint"] == "FK_ENC_PT"
        assert edge["source_table_key"] == "DEMIS_OWNER.TB_ENC_HIST"
        assert edge["target_table_key"] == "DEMIS_OWNER.TB_PT_MST"
        assert edge["column_mapping"] == [
            {"source": "PT_ID", "target": "PT_ID", "ordinal_position": 1}
        ]
    finally:
        _cleanup(source_id)


def test_erd_graph_unknown_source_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/schema/erd", params={"source_id": 999999999})
    assert response.status_code == 404
    assert response.json()["detail"] == "catalog source not found"
