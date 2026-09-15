"""Embedding provider abstractions and implementations."""

from __future__ import annotations

from app.embeddings.base import EmbeddingProvider
from app.embeddings.errors import EmbeddingError
from app.embeddings.factory import (
    clear_runtime_embedding_provider_cache,
    get_embedding_provider,
    get_runtime_embedding_provider,
)
from app.embeddings.fake import FakeEmbeddingProvider

__all__ = [
    "EmbeddingError",
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "clear_runtime_embedding_provider_cache",
    "get_embedding_provider",
    "get_runtime_embedding_provider",
]
