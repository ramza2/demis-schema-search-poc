"""Step 3 Embedding Pipeline / Search Document / pgvector tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ["EMBEDDING_PROVIDER"] = "fake"


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture(scope="module")
def catalog_engine():
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("MEDICAL_DB_HOST", "localhost")
    os.environ.setdefault("MEDICAL_DB_PORT", "5433")
    os.environ.setdefault("CATALOG_DB_HOST", "localhost")
    os.environ.setdefault("CATALOG_DB_PORT", "5434")
    os.environ["EMBEDDING_PROVIDER"] = "fake"

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        analyze = test_client.post("/api/v1/schema/analyze")
        assert analyze.status_code == 200, analyze.text
        rebuild = test_client.post("/api/v1/embeddings/documents/rebuild")
        assert rebuild.status_code == 200, rebuild.text
        yield test_client, analyze.json(), rebuild.json()


def test_pgvector_extension_enabled(catalog_engine) -> None:
    with catalog_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        ).scalar()
    assert exists is True


def test_search_document_rebuild_counts(client) -> None:
    test_client, analyzed, rebuilt = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])
    assert rebuilt["tables"] == analyzed["tables"] == 24
    assert rebuilt["columns"] == analyzed["columns"]
    assert rebuilt["documents"] == expected_docs

    second = test_client.post("/api/v1/embeddings/documents/rebuild")
    assert second.status_code == 200, second.text
    again = second.json()
    assert again["documents"] == expected_docs
    assert again["created"] == 0
    assert again["unchanged"] == expected_docs


def test_table_document_content_tb_lab_rst(client) -> None:
    test_client, _, _ = client
    docs = test_client.get(
        "/api/v1/embeddings/documents",
        params={"object_type": "TABLE", "name": "tb_lab_rst", "limit": 20},
    )
    assert docs.status_code == 200, docs.text
    rows = docs.json()
    assert rows
    detail = test_client.get(f"/api/v1/embeddings/documents/{rows[0]['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()["searchable_text"]
    assert "Object Type: TABLE" in body
    assert "tb_lab_rst" in body
    assert "Primary Key:" in body
    assert "Foreign Keys:" in body
    assert "임상검사 결과" in body or "Description:" in body
    assert "exm_cd" in body


def test_column_document_content_exm_cd(client) -> None:
    test_client, _, _ = client
    docs = test_client.get(
        "/api/v1/embeddings/documents",
        params={"object_type": "COLUMN", "name": "tb_lab_rst:exm_cd", "limit": 50},
    )
    assert docs.status_code == 200, docs.text
    rows = docs.json()
    assert rows, docs.text
    detail = test_client.get(f"/api/v1/embeddings/documents/{rows[0]['id']}")
    body = detail.json()["searchable_text"]
    assert "Object Type: COLUMN" in body
    assert "tb_lab_rst" in body
    assert "exm_cd" in body
    assert "tb_lab_mst" in body
    assert "Data Type:" in body
    assert "검사코드" in body


def test_no_seed_row_data_in_search_documents(client) -> None:
    test_client, _, _ = client
    docs = test_client.get("/api/v1/embeddings/documents", params={"limit": 1000})
    assert docs.status_code == 200
    banned = ["홍길동", "김철수", "이영희", "PT0001", "환자성명 예시", "의료문서 본문"]
    seed_codes = ["\nAST\n", "\nALT\n", "\nGGT\n", " AST ", " ALT ", " GGT "]
    for row in docs.json():
        detail = test_client.get(f"/api/v1/embeddings/documents/{row['id']}")
        text_body = detail.json()["searchable_text"]
        for token in banned:
            assert token not in text_body
        for token in seed_codes:
            assert token not in text_body


def test_search_document_idempotency_fingerprints(client, catalog_engine) -> None:
    test_client, analyzed, _ = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])
    test_client.post("/api/v1/embeddings/documents/rebuild")
    with catalog_engine.connect() as conn:
        before = conn.execute(
            text(
                "SELECT document_key, document_fingerprint FROM catalog_search_document "
                "WHERE active ORDER BY document_key"
            )
        ).fetchall()
    test_client.post("/api/v1/embeddings/documents/rebuild")
    with catalog_engine.connect() as conn:
        after = conn.execute(
            text(
                "SELECT document_key, document_fingerprint FROM catalog_search_document "
                "WHERE active ORDER BY document_key"
            )
        ).fetchall()
        count = conn.execute(
            text("SELECT count(*) FROM catalog_search_document WHERE active")
        ).scalar()
    assert before == after
    assert count == expected_docs


def test_fingerprint_changes_when_comment_changes() -> None:
    from app.services.search_document_builder import (
        build_column_searchable_text,
        document_fingerprint_for,
    )

    base = build_column_searchable_text(
        schema_name="public",
        table_name="tb_lab_rst",
        table_comment="lab result",
        column_name="exm_cd",
        column_comment="검사코드",
        data_type="character varying",
        is_primary_key=False,
        is_unique=False,
        foreign_keys=[
            {
                "target_schema": "public",
                "target_table": "tb_lab_mst",
                "target_columns": ["exm_cd"],
            }
        ],
    )
    changed = build_column_searchable_text(
        schema_name="public",
        table_name="tb_lab_rst",
        table_comment="lab result",
        column_name="exm_cd",
        column_comment="검사코드(변경)",
        data_type="character varying",
        is_primary_key=False,
        is_unique=False,
        foreign_keys=[
            {
                "target_schema": "public",
                "target_table": "tb_lab_mst",
                "target_columns": ["exm_cd"],
            }
        ],
    )
    fp1 = document_fingerprint_for(
        document_key="column:1:public:tb_lab_rst:exm_cd", searchable_text=base
    )
    fp2 = document_fingerprint_for(
        document_key="column:1:public:tb_lab_rst:exm_cd", searchable_text=changed
    )
    assert fp1 != fp2


def test_fake_embedding_and_idempotency(client, catalog_engine) -> None:
    test_client, analyzed, _ = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])

    # Ensure a clean slate for this model_key so the first run embeds all docs.
    with catalog_engine.begin() as conn:
        conn.execute(text("DELETE FROM catalog_embedding"))

    first = test_client.post("/api/v1/embeddings/run")
    assert first.status_code == 200, first.text
    r1 = first.json()
    assert r1["status"] == "SUCCESS"
    assert r1["documents"] == expected_docs
    assert r1["embedded"] == expected_docs
    assert r1["skipped"] == 0
    assert r1["failed"] == 0

    second = test_client.post("/api/v1/embeddings/run")
    assert second.status_code == 200, second.text
    r2 = second.json()
    assert r2["status"] == "SUCCESS"
    assert r2["documents"] == expected_docs
    assert r2["embedded"] == 0
    assert r2["skipped"] == expected_docs
    assert r2["failed"] == 0


def test_changed_document_reembedding(client, catalog_engine) -> None:
    test_client, analyzed, _ = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])
    test_client.post("/api/v1/embeddings/run")

    # Avoid SQLAlchemy bind params: do not put ":name" literals in SQL text.
    with catalog_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE catalog_search_document
                SET searchable_text = searchable_text || E'\\nNote: fingerprint-bust',
                    document_fingerprint = encode(
                        sha256(convert_to(document_fingerprint || '-changed', 'UTF8')),
                        'hex'
                    )
                WHERE document_key LIKE :pattern
                  AND object_type = 'TABLE'
                  AND active
                """
            ),
            {"pattern": "%:tb_lab_rst"},
        )

    run = test_client.post("/api/v1/embeddings/run")
    assert run.status_code == 200, run.text
    payload = run.json()
    assert payload["embedded"] == 1
    assert payload["skipped"] == expected_docs - 1


def test_model_key_change_triggers_reembed(client) -> None:
    test_client, analyzed, _ = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])
    test_client.post("/api/v1/embeddings/run")

    os.environ["EMBEDDING_MAX_SEQ_LENGTH"] = "512"
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as alt_client:
        run = alt_client.post("/api/v1/embeddings/run")
        assert run.status_code == 200, run.text
        payload = run.json()
        assert payload["embedded"] == expected_docs
        assert payload["skipped"] == 0

    os.environ["EMBEDDING_MAX_SEQ_LENGTH"] = "1024"
    get_settings.cache_clear()


def test_dimension_mismatch_error_class() -> None:
    from app.embeddings.bge_m3 import DimensionMismatchError

    with pytest.raises(DimensionMismatchError):
        raise DimensionMismatchError("Expected dimension 1024, got 3")


def test_embedding_stats_and_runs(client) -> None:
    test_client, analyzed, _ = client
    expected_docs = int(analyzed["tables"]) + int(analyzed["columns"])
    test_client.post("/api/v1/embeddings/run")

    stats = test_client.get("/api/v1/embeddings/stats")
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["active_documents"] == expected_docs
    assert body["table_documents"] == 24
    assert body["column_documents"] == analyzed["columns"]
    assert body["embedding_count"] >= expected_docs
    assert body["stale_documents"] == 0

    runs = test_client.get("/api/v1/embeddings/runs")
    assert runs.status_code == 200
    assert len(runs.json()) >= 1
    run_id = runs.json()[0]["id"]
    detail = test_client.get(f"/api/v1/embeddings/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id


def test_credential_safety_in_embedding_errors(client) -> None:
    test_client, _, _ = client
    resp = test_client.post(
        "/api/v1/embeddings/documents/rebuild", params={"source": "no_such_source"}
    )
    assert resp.status_code == 404
    detail = str(resp.json())
    assert "catalog_pass_change_me" not in detail
    assert "medical_pass_change_me" not in detail
    assert "postgresql+psycopg://" not in detail
