"""Embedding provider abstractions and implementations."""

from __future__ import annotations

from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.embeddings.fake import FakeEmbeddingProvider

__all__ = [
    "EmbeddingProvider",
    "FakeEmbeddingProvider",
    "get_embedding_provider",
]
