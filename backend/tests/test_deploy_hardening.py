"""Deploy hardening: optional medical health, embedding source filters, semantic isolation, Oracle probe."""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.config import Settings, get_settings
from app.db.session import get_catalog_session_factory
from app.db.target_connection import probe_connection
from app.embeddings.factory import get_embedding_provider
from app.models.catalog import (
    CatalogEmbedding,
    CatalogSearchDocument,
    CatalogSource,
    CatalogTable,
)
from app.services.fingerprint import fingerprint
from app.services.health import build_health_payload
from app.services.search_document_builder import column_document_key, table_document_key


def _catalog_env() -> None:
    os.environ.setdefault("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    os.environ.setdefault("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    os.environ.setdefault("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    os.environ.setdefault("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"


def _delete_source(source_id: int) -> None:
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
            text(
                "DELETE FROM catalog_embedding WHERE search_document_id IN "
                "(SELECT id FROM catalog_search_document WHERE source_id = :sid)"
            ),
            {"sid": source_id},
        )
        session.execute(
            text("DELETE FROM catalog_embedding_run WHERE source_id = :sid"),
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
    from app.db import session as session_mod
    from app.db.catalog_bootstrap import ensure_catalog_schema
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    ensure_catalog_schema()

    with TestClient(create_app()) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1. Production health — medical_demo optional
# ---------------------------------------------------------------------------


def test_health_medical_required_failure_is_degraded() -> None:
    settings = Settings(medical_db_required=True)
    with (
        patch("app.services.health.check_connection") as mock_check,
        patch("app.services.health.get_catalog_engine") as mock_catalog_engine,
        patch("app.services.health.get_medical_engine") as mock_medical_engine,
    ):
        mock_check.side_effect = [True, False]
        payload = build_health_payload(settings)

    assert payload["status"] == "degraded"
    assert payload["catalog_db"] == "ok"
    assert payload["medical_db"] == "error"
    assert payload["medical_db_required"] is True
    mock_catalog_engine.assert_called_once()
    mock_medical_engine.assert_called_once()
    assert mock_check.call_count == 2


def test_health_medical_optional_skips_medical_connection_when_catalog_ok() -> None:
    settings = Settings(medical_db_required=False)
    with (
        patch("app.services.health.check_connection") as mock_check,
        patch("app.services.health.get_catalog_engine") as mock_catalog_engine,
        patch("app.services.health.get_medical_engine") as mock_medical_engine,
    ):
        mock_check.return_value = True
        payload = build_health_payload(settings)

    assert payload["status"] == "ok"
    assert payload["backend"] == "ok"
    assert payload["catalog_db"] == "ok"
    assert payload["medical_db"] == "disabled"
    assert payload["medical_db_required"] is False
    mock_catalog_engine.assert_called_once()
    mock_medical_engine.assert_not_called()
    mock_check.assert_called_once()


def test_health_medical_optional_skips_medical_connection_when_catalog_fails() -> None:
    settings = Settings(medical_db_required=False)
    with (
        patch("app.services.health.check_connection") as mock_check,
        patch("app.services.health.get_catalog_engine") as mock_catalog_engine,
        patch("app.services.health.get_medical_engine") as mock_medical_engine,
    ):
        mock_check.return_value = False
        payload = build_health_payload(settings)

    assert payload["status"] == "degraded"
    assert payload["catalog_db"] == "error"
    assert payload["medical_db"] == "disabled"
    assert payload["medical_db_required"] is False
    mock_catalog_engine.assert_called_once()
    mock_medical_engine.assert_not_called()
    mock_check.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Oracle V$VERSION fallback
# ---------------------------------------------------------------------------


def _mock_oracle_engine(*, version_behavior: str) -> MagicMock:
    """version_behavior: 'ok' | 'denied' | 'empty'."""

    def execute(statement, *args, **kwargs):
        sql = str(statement)
        result = MagicMock()
        if "v$version" in sql.lower():
            if version_behavior == "denied":
                raise Exception("ORA-00942: table or view does not exist")
            if version_behavior == "empty":
                result.mappings.return_value.first.return_value = None
            else:
                result.mappings.return_value.first.return_value = {
                    "version": "Oracle Database 19c Enterprise Edition"
                }
            return result
        if "SYS_CONTEXT" in sql.upper():
            result.mappings.return_value.one.return_value = {"svc": "ORCLPDB1"}
            return result
        result.mappings.return_value.one.return_value = {"current_user": "APP"}
        return result

    conn = MagicMock()
    conn.execute.side_effect = execute
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    return engine


def test_oracle_probe_succeeds_without_v_version() -> None:
    result = probe_connection(_mock_oracle_engine(version_behavior="denied"), "oracle")
    assert result["connected"] is True
    assert result["dbms_product"] == "Oracle"
    assert result["db_version"] == "unavailable"
    assert result["database_or_service"] == "ORCLPDB1"
    assert result["current_user"] == "APP"
    blob = str(result).lower()
    assert "password" not in blob
    assert "secret" not in blob


def test_oracle_probe_returns_version_when_allowed() -> None:
    result = probe_connection(_mock_oracle_engine(version_behavior="ok"), "oracle")
    assert result["connected"] is True
    assert result["db_version"] == "Oracle Database 19c Enterprise Edition"


def test_oracle_probe_uses_oracle_label_when_empty() -> None:
    result = probe_connection(_mock_oracle_engine(version_behavior="empty"), "oracle")
    assert result["connected"] is True
    assert result["db_version"] == "Oracle"


# ---------------------------------------------------------------------------
# Shared helpers for source isolation
# ---------------------------------------------------------------------------


def _seed_pair(prefix: str, marker_a: str, marker_b: str) -> tuple[int, int, str, str]:
    session = get_catalog_session_factory()()
    try:
        source_a = CatalogSource(
            source_name=f"{prefix}_a",
            db_type="postgresql",
            host="localhost",
            port=5432,
            database_name="iso_a",
            default_schema="public",
            username="u_a",
            enabled=True,
        )
        source_b = CatalogSource(
            source_name=f"{prefix}_b",
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
        source_a_id = int(source_a.id)
        source_b_id = int(source_b.id)

        for sid, marker in ((source_a_id, marker_a), (source_b_id, marker_b)):
            table = CatalogTable(
                source_id=sid,
                schema_name="public",
                table_name="orders",
                table_type="BASE TABLE",
                table_comment=marker,
                object_fingerprint=fingerprint({"t": marker}),
                active=True,
            )
            session.add(table)
            session.flush()

            table_key = table_document_key(sid, "public", "orders")
            table_text = f"public orders {marker}"
            session.add(
                CatalogSearchDocument(
                    source_id=sid,
                    object_type="TABLE",
                    table_id=int(table.id),
                    column_id=None,
                    document_key=table_key,
                    searchable_text=table_text,
                    source_fingerprint=fingerprint({"t": marker}),
                    document_fingerprint=fingerprint({"k": table_key, "t": table_text}),
                    builder_version="test",
                    active=True,
                )
            )

            col_key = column_document_key(sid, "public", "orders", "id")
            col_text = f"public orders.id {marker}_col"
            session.add(
                CatalogSearchDocument(
                    source_id=sid,
                    object_type="COLUMN",
                    table_id=int(table.id),
                    column_id=None,
                    document_key=col_key,
                    searchable_text=col_text,
                    source_fingerprint=fingerprint({"c": marker}),
                    document_fingerprint=fingerprint({"k": col_key, "t": col_text}),
                    builder_version="test",
                    active=True,
                )
            )

        session.commit()
        return (
            source_a_id,
            source_b_id,
            table_document_key(source_a_id, "public", "orders"),
            table_document_key(source_b_id, "public", "orders"),
        )
    finally:
        session.close()


def _embed_source(source_id: int) -> None:
    session = get_catalog_session_factory()()
    try:
        provider = get_embedding_provider(get_settings())
        docs = session.scalars(
            select(CatalogSearchDocument).where(
                CatalogSearchDocument.source_id == source_id,
                CatalogSearchDocument.active.is_(True),
            )
        ).all()
        vectors = provider.embed_texts([d.searchable_text for d in docs])
        for doc, vector in zip(docs, vectors, strict=True):
            session.add(
                CatalogEmbedding(
                    search_document_id=doc.id,
                    model_key=provider.model_key,
                    model_name=provider.model_name,
                    model_revision=provider.model_revision,
                    dimension=provider.dimension,
                    normalized=provider.normalized,
                    document_fingerprint=doc.document_fingerprint,
                    embedding=vector,
                )
            )
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 2. Embedding stats / documents source isolation
# ---------------------------------------------------------------------------


def test_embedding_stats_and_documents_isolated_by_source(client) -> None:
    prefix = f"emb_iso_{uuid.uuid4().hex[:8]}"
    source_ids: list[int] = []
    try:
        source_a_id, source_b_id, _, _ = _seed_pair(
            prefix, "TARGET_A_MARKER_ALPHA", "TARGET_B_MARKER_BETA"
        )
        source_ids = [source_a_id, source_b_id]
        _embed_source(source_a_id)
        _embed_source(source_b_id)

        all_stats = client.get("/api/v1/embeddings/stats").json()
        assert all_stats["active_documents"] >= 4
        assert all_stats["embedding_count"] >= 4
        assert all_stats.get("source_id") is None

        stats_a = client.get(
            "/api/v1/embeddings/stats",
            params={"source_id": source_a_id},
        ).json()
        stats_b = client.get(
            "/api/v1/embeddings/stats",
            params={"source_id": source_b_id},
        ).json()

        assert stats_a["source_id"] == source_a_id
        assert stats_b["source_id"] == source_b_id
        assert stats_a["active_documents"] == 2
        assert stats_b["active_documents"] == 2
        assert stats_a["table_documents"] == 1
        assert stats_b["table_documents"] == 1
        assert stats_a["column_documents"] == 1
        assert stats_b["column_documents"] == 1
        assert stats_a["embedding_count"] == 2
        assert stats_b["embedding_count"] == 2
        assert stats_a["stale_documents"] == 0
        assert stats_b["stale_documents"] == 0

        docs_a = client.get(
            "/api/v1/embeddings/documents",
            params={"source_id": source_a_id},
        ).json()
        docs_b = client.get(
            "/api/v1/embeddings/documents",
            params={"source_id": source_b_id},
        ).json()
        assert {row["source_id"] for row in docs_a} == {source_a_id}
        assert {row["source_id"] for row in docs_b} == {source_b_id}
        assert len(docs_a) == 2
        assert len(docs_b) == 2

        by_name = client.get(
            "/api/v1/embeddings/stats",
            params={"source_name": f"{prefix}_a"},
        ).json()
        assert by_name["source_id"] == source_a_id
        assert by_name["active_documents"] == 2
        assert by_name["source_name"] == f"{prefix}_a"
    finally:
        for sid in source_ids:
            try:
                _delete_source(sid)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# 3. Semantic search multi-target isolation
# ---------------------------------------------------------------------------


def test_semantic_search_isolated_by_source_id(client) -> None:
    prefix = f"sem_iso_{uuid.uuid4().hex[:8]}"
    source_ids: list[int] = []
    try:
        source_a_id, source_b_id, key_a, key_b = _seed_pair(
            prefix, "TARGET_A_MARKER_ALPHA", "TARGET_B_MARKER_BETA"
        )
        source_ids = [source_a_id, source_b_id]
        _embed_source(source_a_id)
        _embed_source(source_b_id)

        response_a = client.post(
            "/api/v1/search/schema",
            json={
                "query": "TARGET_A_MARKER_ALPHA",
                "mode": "semantic",
                "source_id": source_a_id,
                "top_k": 10,
                "expand_terms": False,
                "expand_relations": False,
            },
        )
        assert response_a.status_code == 200, response_a.text
        payload_a = response_a.json()
        assert payload_a["mode"] == "semantic"
        assert payload_a["source_id"] == source_a_id
        keys_a = {row["document_key"] for row in payload_a["direct_results"]}
        assert key_a in keys_a
        assert key_b not in keys_a

        response_b = client.post(
            "/api/v1/search/schema",
            json={
                "query": "TARGET_B_MARKER_BETA",
                "mode": "semantic",
                "source_id": source_b_id,
                "top_k": 10,
                "expand_terms": False,
                "expand_relations": False,
            },
        )
        assert response_b.status_code == 200, response_b.text
        keys_b = {row["document_key"] for row in response_b.json()["direct_results"]}
        assert key_b in keys_b
        assert key_a not in keys_b

        cross = client.post(
            "/api/v1/search/schema",
            json={
                "query": "TARGET_B_MARKER_BETA",
                "mode": "semantic",
                "source_id": source_a_id,
                "top_k": 20,
                "expand_terms": False,
                "expand_relations": False,
            },
        )
        assert cross.status_code == 200, cross.text
        cross_keys = {row["document_key"] for row in cross.json()["direct_results"]}
        assert key_b not in cross_keys
    finally:
        for sid in source_ids:
            try:
                _delete_source(sid)
            except Exception:  # noqa: BLE001
                pass
