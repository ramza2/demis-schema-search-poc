"""Unit tests for OpenAI-compatible embedding provider (httpx mocked; no live API)."""

from __future__ import annotations

import json
import math
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.config import Settings
from app.embeddings.errors import (
    ConfigurationError,
    DimensionMismatchError,
    EmbeddingFailedError,
    InvalidResponseError,
    RequestTimeoutError,
)
from app.embeddings.factory import get_embedding_provider
from app.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.services.embedding_service import EmbeddingService


def _unit(dim: int = 1024, scale: float = 1.0) -> list[float]:
    vec = [0.0] * dim
    vec[0] = scale
    return vec


def _embedding_response(
    vectors: list[list[float]],
    *,
    shuffle_indexes: bool = False,
    model: str = "BAAI/bge-m3",
) -> dict[str, Any]:
    items = [
        {"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(vectors)
    ]
    if shuffle_indexes and len(items) > 1:
        items = list(reversed(items))
    return {"object": "list", "data": items, "model": model}


def _provider(
    transport: httpx.BaseTransport,
    *,
    api_key: str | None = None,
    normalize: bool = True,
    dimension: int = 1024,
) -> OpenAICompatibleEmbeddingProvider:
    return OpenAICompatibleEmbeddingProvider(
        api_url="https://alzi-embedding.openlink.kr/",
        model_name="BAAI/bge-m3",
        api_key=api_key,
        timeout_seconds=5.0,
        dimension=dimension,
        normalize=normalize,
        max_seq_length=1024,
        transport=transport,
    )


def test_single_input_1024_dimension() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["headers"] = {k.lower(): v for k, v in request.headers.items()}
        return httpx.Response(200, json=_embedding_response([_unit()]))

    provider = _provider(httpx.MockTransport(handler))
    vectors = provider.embed_texts(["hello schema"])
    assert len(vectors) == 1
    assert len(vectors[0]) == 1024
    assert captured["url"].endswith("/v1/embeddings")
    assert captured["body"]["model"] == "BAAI/bge-m3"
    assert captured["body"]["input"] == ["hello schema"]
    assert "authorization" not in captured["headers"]


def test_batch_preserves_index_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["input"] == ["a", "b", "c"]
        return httpx.Response(
            200,
            json=_embedding_response(
                [_unit(scale=1.0), _unit(scale=2.0), _unit(scale=3.0)],
                shuffle_indexes=True,
            ),
        )

    provider = _provider(httpx.MockTransport(handler), normalize=False)
    vectors = provider.embed_texts(["a", "b", "c"])
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]


def test_l2_normalize() -> None:
    raw = [3.0, 4.0] + [0.0] * 1022

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([raw]))

    provider = _provider(httpx.MockTransport(handler), normalize=True)
    vectors = provider.embed_texts(["norm"])
    assert math.isclose(vectors[0][0], 0.6, rel_tol=1e-6)
    assert math.isclose(vectors[0][1], 0.8, rel_tol=1e-6)
    assert math.isclose(math.sqrt(sum(v * v for v in vectors[0])), 1.0, rel_tol=1e-6)


def test_dimension_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([[0.1, 0.2, 0.3]]))

    provider = _provider(httpx.MockTransport(handler), dimension=1024)
    with pytest.raises(DimensionMismatchError) as exc:
        provider.embed_texts(["bad-dim"])
    assert exc.value.code == "DIMENSION_MISMATCH"


def test_count_mismatch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([_unit()]))

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(InvalidResponseError) as exc:
        provider.embed_texts(["one", "two"])
    assert exc.value.code == "INVALID_RESPONSE"


def test_http_4xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(EmbeddingFailedError) as exc:
        provider.embed_texts(["x"])
    assert "401" in str(exc.value)
    assert "unauthorized" not in str(exc.value).lower()


def test_http_5xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream boom secret-token")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(EmbeddingFailedError) as exc:
        provider.embed_texts(["x"])
    assert "503" in str(exc.value)
    assert "secret-token" not in str(exc.value)


def test_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(RequestTimeoutError) as exc:
        provider.embed_texts(["x"])
    assert exc.value.code == "REQUEST_TIMEOUT"


def test_malformed_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{not-json")

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(InvalidResponseError):
        provider.embed_texts(["x"])


def test_malformed_response_missing_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list"})

    provider = _provider(httpx.MockTransport(handler))
    with pytest.raises(InvalidResponseError):
        provider.embed_texts(["x"])


def test_optional_authorization_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(200, json=_embedding_response([_unit()]))

    provider = _provider(httpx.MockTransport(handler), api_key="secret-key-value")
    provider.embed_texts(["auth"])
    assert seen["authorization"] == "Bearer secret-key-value"


def test_model_key_includes_provider_not_url() -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        api_url="https://alzi-embedding.openlink.kr",
        model_name="BAAI/bge-m3",
        dimension=1024,
        normalize=True,
        max_seq_length=1024,
    )
    key = provider.model_key
    assert key == (
        "BAAI/bge-m3|provider=openai_compatible|rev=default|dim=1024|norm=true|maxlen=1024"
    )
    assert "openlink" not in key
    assert "http" not in key


def test_factory_selects_openai_compatible() -> None:
    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_api_url="https://alzi-embedding.openlink.kr",
        embedding_model_name="BAAI/bge-m3",
        embedding_dimension=1024,
        embedding_normalize=True,
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert "provider=openai_compatible" in provider.model_key


def test_factory_unknown_provider_fails() -> None:
    settings = Settings(embedding_provider="unknown_vendor")
    with pytest.raises(ConfigurationError) as exc:
        get_embedding_provider(settings)
    assert exc.value.code == "CONFIGURATION_ERROR"
    assert "unknown_vendor" in str(exc.value)


def test_factory_requires_api_url() -> None:
    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_api_url=None,
    )
    with pytest.raises(ConfigurationError):
        get_embedding_provider(settings)


def test_zero_norm_vector_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_embedding_response([[0.0] * 1024]))

    provider = _provider(httpx.MockTransport(handler), normalize=True)
    with pytest.raises(EmbeddingFailedError):
        provider.embed_texts(["zero"])


def test_api_url_trailing_slash_stripped_in_settings() -> None:
    settings = Settings(embedding_api_url="https://alzi-embedding.openlink.kr/")
    assert settings.embedding_api_url == "https://alzi-embedding.openlink.kr"


def test_embedding_service_uses_openai_compatible_provider() -> None:
    calls: list[list[str]] = []

    class StubProvider(OpenAICompatibleEmbeddingProvider):
        def __init__(self) -> None:
            super().__init__(
                api_url="https://example.test",
                model_name="BAAI/bge-m3",
                dimension=1024,
                normalize=True,
            )

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            calls.append(list(texts))
            return [_unit() for _ in texts]

    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_api_url="https://example.test",
        embedding_dimension=1024,
    )
    provider = StubProvider()
    service = EmbeddingService(MagicMock(), settings=settings, provider=provider)
    assert service.provider.model_key == provider.model_key
    assert "provider=openai_compatible" in service.provider.model_key
    out = service.provider.embed_texts(["doc text"])
    assert calls == [["doc text"]]
    assert len(out[0]) == 1024


def test_semantic_query_uses_same_provider_model_key() -> None:
    settings = Settings(
        embedding_provider="openai_compatible",
        embedding_api_url="https://alzi-embedding.openlink.kr",
        embedding_model_name="BAAI/bge-m3",
        embedding_dimension=1024,
        embedding_normalize=True,
        embedding_max_seq_length=1024,
    )
    doc_provider = get_embedding_provider(settings)
    query_provider = get_embedding_provider(settings)
    assert doc_provider.model_key == query_provider.model_key
    assert doc_provider.model_key == (
        "BAAI/bge-m3|provider=openai_compatible|rev=default|dim=1024|norm=true|maxlen=1024"
    )
