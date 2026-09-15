"""Runtime embedding provider cache — process-lifetime reuse for search."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("EMBEDDING_PROVIDER", "fake")
os.environ.setdefault("ALLOW_FAKE_SEMANTIC_SEARCH", "true")


@pytest.fixture(autouse=True)
def _clear_runtime_cache() -> None:
    from app.embeddings.factory import clear_runtime_embedding_provider_cache

    clear_runtime_embedding_provider_cache()
    yield
    clear_runtime_embedding_provider_cache()


def test_runtime_provider_returns_same_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("ALLOW_FAKE_SEMANTIC_SEARCH", "true")

    from app.core.config import get_settings
    from app.embeddings.factory import (
        clear_runtime_embedding_provider_cache,
        get_runtime_embedding_provider,
    )

    get_settings.cache_clear()
    clear_runtime_embedding_provider_cache()

    first = get_runtime_embedding_provider()
    second = get_runtime_embedding_provider()
    assert first is second


def test_runtime_provider_cache_clear_creates_new_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("ALLOW_FAKE_SEMANTIC_SEARCH", "true")

    from app.core.config import get_settings
    from app.embeddings.factory import (
        clear_runtime_embedding_provider_cache,
        get_runtime_embedding_provider,
    )

    get_settings.cache_clear()
    clear_runtime_embedding_provider_cache()

    first = get_runtime_embedding_provider()
    clear_runtime_embedding_provider_cache()
    second = get_runtime_embedding_provider()
    assert first is not second


def test_hybrid_api_reuses_runtime_provider_across_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """semantic/hybrid must inject the cached runtime provider across requests."""
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("ALLOW_FAKE_SEMANTIC_SEARCH", "true")
    monkeypatch.setenv("MEDICAL_DB_HOST", "localhost")
    monkeypatch.setenv("MEDICAL_DB_PORT", "5433")
    monkeypatch.setenv("CATALOG_DB_HOST", "localhost")
    monkeypatch.setenv("CATALOG_DB_PORT", "5434")
    monkeypatch.setenv("EMBEDDING_MAX_SEQ_LENGTH", "1024")

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.embeddings.factory import (
        clear_runtime_embedding_provider_cache,
        get_runtime_embedding_provider,
    )
    from app.main import create_app
    import app.api.search as search_api

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    clear_runtime_embedding_provider_cache()

    constructed: list[object] = []
    real_ctor = search_api.SchemaSearchService

    class TrackingService(real_ctor):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            constructed.append(kwargs.get("provider"))
            super().__init__(*args, **kwargs)

    with patch.object(search_api, "SchemaSearchService", TrackingService):
        with TestClient(create_app()) as client:
            assert client.post("/api/v1/schema/analyze").status_code == 200
            assert (
                client.post("/api/v1/embeddings/documents/rebuild").status_code == 200
            )
            run = client.post("/api/v1/embeddings/run")
            assert run.status_code == 200, run.text

            clear_runtime_embedding_provider_cache()
            constructed.clear()

            payload = {
                "query": "환자 검사 결과",
                "mode": "hybrid",
                "top_k": 5,
                "expand_terms": True,
                "expand_relations": False,
            }
            r1 = client.post("/api/v1/search/schema", json=payload)
            r2 = client.post("/api/v1/search/schema", json=payload)
            assert r1.status_code == 200, r1.text
            assert r2.status_code == 200, r2.text

            assert len(constructed) >= 2
            assert constructed[0] is not None
            assert constructed[1] is not None
            assert constructed[0] is constructed[1]
            assert constructed[0] is get_runtime_embedding_provider()


def test_keyword_api_does_not_initialize_embedding_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("ALLOW_FAKE_SEMANTIC_SEARCH", "true")
    monkeypatch.setenv("MEDICAL_DB_HOST", "localhost")
    monkeypatch.setenv("MEDICAL_DB_PORT", "5433")
    monkeypatch.setenv("CATALOG_DB_HOST", "localhost")
    monkeypatch.setenv("CATALOG_DB_PORT", "5434")

    from app.core.config import get_settings
    from app.db import session as session_mod
    from app.embeddings.factory import clear_runtime_embedding_provider_cache
    from app.main import create_app
    import app.api.search as search_api

    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    clear_runtime_embedding_provider_cache()

    mocked = MagicMock(side_effect=AssertionError("runtime provider must not init"))
    with patch.object(search_api, "get_runtime_embedding_provider", mocked):
        with TestClient(create_app()) as client:
            assert client.post("/api/v1/schema/analyze").status_code == 200
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
            mocked.assert_not_called()
