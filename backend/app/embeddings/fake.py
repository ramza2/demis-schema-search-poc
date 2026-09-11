"""Deterministic Fake Embedding Provider for tests / offline CI."""

from __future__ import annotations

import hashlib
import math
import struct

from app.embeddings.base import EmbeddingProvider


class FakeEmbeddingProvider(EmbeddingProvider):
    """
    Produce deterministic 1024-d vectors from input text.

    Does not download models or use the network.
    """

    def __init__(
        self,
        *,
        dimension: int = 1024,
        normalize: bool = True,
        model_name: str = "fake-embedding",
        model_key: str | None = None,
        max_seq_length: int = 1024,
    ) -> None:
        self._dimension = dimension
        self._normalize = normalize
        self._model_name = model_name
        self._max_seq_length = max_seq_length
        self._model_key = model_key or (
            f"{model_name}|rev=default|dim={dimension}"
            f"|norm={'true' if normalize else 'false'}|maxlen={max_seq_length}"
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
        return "default"

    @property
    def normalized(self) -> bool:
        return self._normalize

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        seed = digest
        while len(values) < self._dimension:
            # Expand digest stream deterministically.
            seed = hashlib.sha256(seed).digest()
            for i in range(0, len(seed), 4):
                if len(values) >= self._dimension:
                    break
                (unsigned,) = struct.unpack_from(">I", seed, i)
                # Map to [-1, 1]
                values.append((unsigned / 0xFFFFFFFF) * 2.0 - 1.0)

        if self._normalize:
            norm = math.sqrt(sum(v * v for v in values)) or 1.0
            values = [v / norm for v in values]
        return values
