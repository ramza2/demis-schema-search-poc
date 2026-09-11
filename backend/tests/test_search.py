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



def test_generic_query_does_not_trigger_lab_concepts() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("검사결과")
    assert "liver_function" not in exp.matched_concepts
    assert "blood_glucose" not in exp.matched_concepts
    assert "renal_function" not in exp.matched_concepts


def test_liver_query_triggers_and_expands() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("최근 간수치 검사 결과")
    assert "liver_function" in exp.matched_concepts
    assert "AST" in exp.expanded_terms
    assert "ALT" in exp.expanded_terms


def test_diagnosis_history_does_not_trigger_hypertension() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("진단 이력")
    assert "hypertension" not in exp.matched_concepts


def test_hypertension_diagnosis_triggers() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("고혈압 진단 이력")
    assert "hypertension" in exp.matched_concepts


def test_clinical_document_does_not_trigger_discharge() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("임상문서")
    assert "discharge_summary" not in exp.matched_concepts


def test_discharge_summary_document_triggers() -> None:
    from app.services.search.terminology import clear_concept_cache, expand_query

    clear_concept_cache()
    exp = expand_query("퇴원요약 문서")
    assert "discharge_summary" in exp.matched_concepts


def test_dictionary_blocks_physical_and_mapping_leakage() -> None:
    from app.services.search.terminology import assert_no_schema_leakage, clear_concept_cache, get_concepts

    clear_concept_cache()
    concepts = get_concepts()
    # Medical terminology like AST/ALT/HbA1c/Creatinine is allowed.
    joined = " ".join(
        " ".join((c.label, *c.triggers, *c.expansion_terms)) for c in concepts
    )
    assert "AST" in joined
    assert "ALT" in joined
    assert assert_no_schema_leakage(concepts) == []
    for c in concepts:
        for term in (c.label, *c.triggers, *c.expansion_terms):
            assert not term.lower().startswith("tb_")
            assert "->" not in term
            assert "→" not in term


def test_relation_expansion_schema_qualified_no_collision() -> None:
    """Same table_name in different schemas must not collide."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.search.relation_expander import expand_relations

    t_pub_rst = SimpleNamespace(id=1, schema_name="public", table_name="tb_lab_rst", active=True)
    t_pub_mst = SimpleNamespace(id=2, schema_name="public", table_name="tb_lab_mst", active=True)
    t_an_rst = SimpleNamespace(id=3, schema_name="analytics", table_name="tb_lab_rst", active=True)
    t_an_mst = SimpleNamespace(id=4, schema_name="analytics", table_name="tb_lab_mst", active=True)

    rel_pub = SimpleNamespace(
        id=10,
        source_table_id=1,
        target_table_id=2,
        constraint_name="fk_pub",
        active=True,
        columns=[],
    )
    rel_an = SimpleNamespace(
        id=11,
        source_table_id=3,
        target_table_id=4,
        constraint_name="fk_an",
        active=True,
        columns=[],
    )

    session = MagicMock()
    calls = {"n": 0}

    def scalars(_stmt):
        calls["n"] += 1
        result = MagicMock()
        if calls["n"] == 1:
            result.all.return_value = [t_pub_rst, t_pub_mst, t_an_rst, t_an_mst]
        elif calls["n"] == 2:
            result.all.return_value = []
        else:
            result.all.return_value = [rel_pub, rel_an]
        return result

    session.scalars.side_effect = scalars

    related = expand_relations(
        session,
        seed_tables=[("public", "tb_lab_rst")],
        max_hops=1,
    )
    assert len(related) == 1
    hit = related[0]
    assert hit.schema_name == "public"
    assert hit.table_name == "tb_lab_mst"
    assert hit.seed_schema == "public"
    assert hit.seed_table == "tb_lab_rst"
    assert hit.result_key == "public.tb_lab_rst->public.tb_lab_mst"
    assert all(r.schema_name != "analytics" for r in related)

    session2 = MagicMock()
    calls2 = {"n": 0}

    def scalars2(_stmt):
        calls2["n"] += 1
        result = MagicMock()
        if calls2["n"] == 1:
            result.all.return_value = [t_pub_rst, t_pub_mst, t_an_rst, t_an_mst]
        elif calls2["n"] == 2:
            result.all.return_value = []
        else:
            result.all.return_value = [rel_pub, rel_an]
        return result

    session2.scalars.side_effect = scalars2
    related_an = expand_relations(
        session2,
        seed_tables=[("analytics", "tb_lab_rst")],
        max_hops=1,
    )
    assert len(related_an) == 1
    assert related_an[0].schema_name == "analytics"
    assert related_an[0].table_name == "tb_lab_mst"
    assert related_an[0].result_key == "analytics.tb_lab_rst->analytics.tb_lab_mst"


def test_search_timings_include_semantic_search_ms(client) -> None:
    resp = client.post(
        "/api/v1/search/schema",
        json={
            "query": "최근 간수치 검사 결과",
            "mode": "hybrid",
            "top_k": 5,
            "expand_terms": True,
            "expand_relations": True,
            "max_relation_hops": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    timings = resp.json()["timings"]
    for key in (
        "query_embedding_ms",
        "semantic_search_ms",
        "keyword_search_ms",
        "relation_expansion_ms",
        "total_ms",
    ):
        assert key in timings
        assert timings[key] >= 0
    rows = resp.json()["direct_results"]
    assert rows
    assert any(r.get("schema_name") == "public" for r in rows)


def test_keyword_mode_timings(client) -> None:
    resp = client.post(
        "/api/v1/search/schema",
        json={
            "query": "tb_lab_rst",
            "mode": "keyword",
            "expand_terms": False,
            "expand_relations": False,
        },
    )
    assert resp.status_code == 200, resp.text
    timings = resp.json()["timings"]
    assert "keyword_search_ms" in timings
    assert timings["keyword_search_ms"] >= 0
    assert "total_ms" in timings
    assert "semantic_search_ms" not in timings
