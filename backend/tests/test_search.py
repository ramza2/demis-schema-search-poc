"""Step 4 schema search tests."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("MEDICAL_DB_HOST", "localhost")
    os.environ.setdefault("MEDICAL_DB_PORT", "5433")
    os.environ.setdefault("CATALOG_DB_HOST", "localhost")
    os.environ.setdefault("CATALOG_DB_PORT", "5434")
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"
    os.environ["EMBEDDING_MAX_SEQ_LENGTH"] = "1024"

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()

    with TestClient(create_app()) as test_client:
        assert test_client.post("/api/v1/schema/analyze").status_code == 200
        assert test_client.post("/api/v1/embeddings/documents/rebuild").status_code == 200
        with create_engine(_catalog_url()).begin() as conn:
            conn.execute(text("DELETE FROM catalog_embedding WHERE model_key LIKE 'fake-embedding%'"))
        run = test_client.post("/api/v1/embeddings/run")
        assert run.status_code == 200, run.text
        yield test_client


def test_query_normalization() -> None:
    from app.services.search.query_normalizer import normalize_query

    n = normalize_query("  Recent   LFT   Values  ")
    assert n.normalized == "recent lft values"


def test_medical_term_expansion_liver() -> None:
    from app.services.search.terminology import expand_query

    exp = expand_query("최근 간수치 검사")
    assert "liver_function" in exp.matched_concepts
    assert "AST" in exp.expanded_terms
    assert "ALT" in exp.expanded_terms


def test_dictionary_has_no_schema_leakage() -> None:
    from app.services.search.terminology import assert_no_schema_leakage

    assert assert_no_schema_leakage() == []


def test_rrf_fusion_deterministic() -> None:
    from app.services.search.rrf import rrf_fuse

    fused = rrf_fuse(
        semantic_hits=[(10, 0.9, ["s"]), (20, 0.8, ["s"]), (30, 0.7, ["s"])],
        keyword_hits=[(20, 50.0, ["k"]), (40, 40.0, ["k"]), (10, 30.0, ["k"])],
        k=60,
    )
    ids = [h.document_id for h in fused]
    assert ids[0] in {10, 20}
    assert set(ids) == {10, 20, 30, 40}


def test_model_key_path_independence(tmp_path) -> None:
    from app.core.config import Settings

    a = Settings(
        embedding_model_name="BAAI/bge-m3",
        embedding_model_path=str(tmp_path / "path-a"),
        embedding_dimension=1024,
        embedding_normalize=True,
        embedding_max_seq_length=1024,
    )
    b = Settings(
        embedding_model_name="BAAI/bge-m3",
        embedding_model_path=str(tmp_path / "path-b"),
        embedding_dimension=1024,
        embedding_normalize=True,
        embedding_max_seq_length=1024,
    )
    assert a.build_model_key() == b.build_model_key()
    assert a.build_model_key().startswith("BAAI/bge-m3|")
    assert "path-a" not in a.build_model_key()


def test_fake_provider_blocked_without_flag() -> None:
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "false"
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    with TestClient(create_app()) as c:
        resp = c.post(
            "/api/v1/search/schema",
            json={"query": "간수치", "mode": "semantic", "expand_relations": False},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "SEMANTIC_PROVIDER_NOT_AVAILABLE"
    os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"
    get_settings.cache_clear()


def test_keyword_physical_identifier(client) -> None:
    resp = client.post(
        "/api/v1/search/schema",
        json={
            "query": "tb_lab_rst",
            "mode": "keyword",
            "top_k": 5,
            "expand_terms": False,
            "expand_relations": False,
        },
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["direct_results"]
    assert rows
    assert any(r["table_name"] == "tb_lab_rst" for r in rows)


def test_keyword_column_identifier(client) -> None:
    resp = client.post(
        "/api/v1/search/schema",
        json={
            "query": "exm_cd",
            "mode": "keyword",
            "object_type": "COLUMN",
            "top_k": 10,
            "expand_terms": False,
            "expand_relations": False,
        },
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["direct_results"]
    assert rows
    assert any(r["column_name"] == "exm_cd" for r in rows)


def test_hybrid_search_with_fake(client) -> None:
    resp = client.post(
        "/api/v1/search/schema",
        json={
            "query": "최근 간수치 검사 결과",
            "mode": "hybrid",
            "top_k": 10,
            "expand_terms": True,
            "expand_relations": True,
            "max_relation_hops": 2,
            "debug": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "hybrid"
    assert "liver_function" in body["query"]["matched_concepts"]
    assert body["direct_results"]
    assert "catalog_pass_change_me" not in str(body)
    assert "postgresql+psycopg://" not in str(body)


def test_relation_expansion_lab_rst() -> None:
    from app.db.session import get_catalog_session_factory
    from app.services.search.relation_expander import expand_relations

    session = get_catalog_session_factory()()
    try:
        related = expand_relations(session, seed_table_names=["tb_lab_rst"], max_hops=1)
        names = {r.table_name for r in related}
        assert {"tb_lab_mst", "tb_lab_ord", "tb_pt_mst", "tb_provider"} <= names
        related2 = expand_relations(session, seed_table_names=["tb_lab_rst"], max_hops=2)
        assert all(r.hop_distance <= 2 for r in related2)
        assert len({r.table_name for r in related2}) >= len(names)
    finally:
        session.close()


def test_relation_hop_limit() -> None:
    from app.db.session import get_catalog_session_factory
    from app.services.search.relation_expander import expand_relations

    session = get_catalog_session_factory()()
    try:
        related = expand_relations(session, seed_table_names=["tb_lab_rst"], max_hops=1)
        assert all(r.hop_distance == 1 for r in related)
    finally:
        session.close()


def test_missing_embedding_model_key_error() -> None:
    os.environ["EMBEDDING_PROVIDER"] = "fake"
    os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"
    os.environ["EMBEDDING_MAX_SEQ_LENGTH"] = "777"
    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.main import create_app

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    with TestClient(create_app()) as c:
        resp = c.post(
            "/api/v1/search/schema",
            json={"query": "간수치", "mode": "semantic", "expand_relations": False},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "EMBEDDING_NOT_FOUND"
    os.environ["EMBEDDING_MAX_SEQ_LENGTH"] = "1024"
    get_settings.cache_clear()


def test_document_query_model_key_alignment(client) -> None:
    from app.core.config import get_settings
    from app.embeddings.factory import get_embedding_provider

    get_settings.cache_clear()
    provider = get_embedding_provider(get_settings())
    stats = client.get("/api/v1/embeddings/stats")
    assert stats.status_code == 200
    keys = stats.json().get("model_keys") or []
    assert provider.model_key in keys


def test_credential_safety_in_search_errors(client) -> None:
    resp = client.post("/api/v1/search/schema", json={"query": "x", "mode": "hybrid"})
    blob = str(resp.json())
    assert "catalog_pass_change_me" not in blob
    assert "medical_pass_change_me" not in blob
