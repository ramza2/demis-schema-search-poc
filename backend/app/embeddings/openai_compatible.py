"""OpenAI-compatible remote Embedding Provider (HTTP, no generative LLM)."""

from __future__ import annotations

import logging
import math
from typing import Any

import httpx

from app.embeddings.base import EmbeddingProvider
from app.embeddings.errors import (
    ConfigurationError,
    DimensionMismatchError,
    EmbeddingFailedError,
    InvalidResponseError,
    RequestTimeoutError,
)

logger = logging.getLogger(__name__)


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm <= 0.0:
        raise EmbeddingFailedError("Received zero-norm embedding vector")
    return [v / norm for v in vector]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """
    Call an OpenAI-compatible POST /v1/embeddings endpoint.

    Document embeddings and query embeddings share the same model_key so
    remote vectors never mix with local/fake embeddings.
    """

    def __init__(
        self,
        *,
        api_url: str,
        model_name: str = "BAAI/bge-m3",
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        dimension: int = 1024,
        normalize: bool = True,
        max_seq_length: int = 1024,
        model_revision: str | None = None,
        model_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        base = (api_url or "").strip().rstrip("/")
        if not base:
            raise ConfigurationError(
                "EMBEDDING_API_URL is required when EMBEDDING_PROVIDER=openai_compatible"
            )
        self._api_url = base
        self._model_name = model_name
        self._api_key = (api_key or "").strip() or None
        self._timeout = float(timeout_seconds)
        self._dimension = int(dimension)
        self._normalize = bool(normalize)
        self._max_seq_length = int(max_seq_length)
        self._model_revision = model_revision or "default"
        self._transport = transport
        rev = self._model_revision
        norm = "true" if self._normalize else "false"
        self._model_key = model_key or (
            f"{self._model_name}|provider=openai_compatible|rev={rev}"
            f"|dim={self._dimension}|norm={norm}|maxlen={self._max_seq_length}"
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_key(self) -> str:
        return self._model_key

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_revision(self) -> str | None:
        return self._model_revision

    @property
    def normalized(self) -> bool:
        return self._normalize

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {"model": self._model_name, "input": texts}
        url = f"{self._api_url}/v1/embeddings"

        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("Embedding API request timed out")
            raise RequestTimeoutError(
                f"Embedding API timed out after {self._timeout:.0f}s"
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("Embedding API transport error: %s", type(exc).__name__)
            raise EmbeddingFailedError(
                f"Embedding API request failed ({type(exc).__name__})"
            ) from exc

        if response.status_code >= 400:
            logger.warning("Embedding API HTTP %s", response.status_code)
            raise EmbeddingFailedError(
                f"Embedding API returned HTTP {response.status_code}"
            )

        try:
            body: Any = response.json()
        except ValueError as exc:
            raise InvalidResponseError("Embedding API returned non-JSON response") from exc

        if not isinstance(body, dict):
            raise InvalidResponseError("Embedding API response is not an object")

        data = body.get("data")
        if not isinstance(data, list):
            raise InvalidResponseError("Embedding API response missing data[]")

        indexed: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise InvalidResponseError("Embedding API data item is not an object")
            if "index" not in item or "embedding" not in item:
                raise InvalidResponseError(
                    "Embedding API data item missing index or embedding"
                )
            try:
                idx = int(item["index"])
            except (TypeError, ValueError) as exc:
                raise InvalidResponseError(
                    "Embedding API data item has invalid index"
                ) from exc
            emb = item["embedding"]
            if not isinstance(emb, list) or not emb:
                raise InvalidResponseError("Embedding API returned empty embedding")
            try:
                vector = [float(x) for x in emb]
            except (TypeError, ValueError) as exc:
                raise InvalidResponseError(
                    "Embedding API embedding contains non-numeric values"
                ) from exc
            if len(vector) != self._dimension:
                raise DimensionMismatchError(
                    f"Expected dimension {self._dimension}, got {len(vector)}"
                )
            if self._normalize:
                vector = _l2_normalize(vector)
            indexed[idx] = vector

        if len(indexed) != len(texts):
            raise InvalidResponseError(
                f"Embedding API returned {len(indexed)} vectors for {len(texts)} texts"
            )
        try:
            return [indexed[i] for i in range(len(texts))]
        except KeyError as exc:
            raise InvalidResponseError(
                "Embedding API data indexes are not contiguous from 0"
            ) from exc
