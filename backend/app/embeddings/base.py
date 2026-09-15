"""Embedding provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract embedding provider (no generative LLM)."""

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one float vector per input text."""

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """Embed search queries.

        Default delegates to ``embed_texts`` so fake / bge_m3 / openai_compatible
        keep their existing behavior. Providers that need asymmetric prefixes
        (e.g. E5 / KoE5) override this method.
        """
        return self.embed_texts(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed catalog / passage documents.

        Default delegates to ``embed_texts`` so fake / bge_m3 / openai_compatible
        keep their existing behavior. Providers that need asymmetric prefixes
        (e.g. E5 / KoE5) override this method.
        """
        return self.embed_texts(texts)

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Human-readable model identity."""

    @property
    @abstractmethod
    def model_key(self) -> str:
        """Stable key incorporating model settings."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Expected vector dimension."""

    @property
    def model_revision(self) -> str | None:
        return None

    @property
    def normalized(self) -> bool:
        return True
