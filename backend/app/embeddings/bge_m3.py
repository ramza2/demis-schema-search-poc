"""BGE-M3 Embedding Provider (CPU-only, lazy load)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.embeddings.base import EmbeddingProvider

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Base embedding error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ModelNotAvailableError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_NOT_AVAILABLE", message)


class ModelLoadFailedError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("MODEL_LOAD_FAILED", message)


class EmbeddingFailedError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("EMBEDDING_FAILED", message)


class DimensionMismatchError(EmbeddingError):
    def __init__(self, message: str) -> None:
        super().__init__("DIMENSION_MISMATCH", message)


class BgeM3EmbeddingProvider(EmbeddingProvider):
    """
    sentence-transformers BGE-M3 provider.

    - device defaults to cpu
    - lazy model load (startup / health must not require the model)
    - prefers local EMBEDDING_MODEL_PATH when present
    """

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-m3",
        model_path: str | None = None,
        model_revision: str | None = None,
        device: str = "cpu",
        dimension: int = 1024,
        batch_size: int = 8,
        max_seq_length: int = 1024,
        normalize: bool = True,
        num_threads: int | None = None,
        hf_hub_offline: bool = False,
        model_key: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._model_path = (model_path or "").strip() or None
        self._model_revision = model_revision
        self._device = device or "cpu"
        self._dimension = dimension
        self._batch_size = max(1, batch_size)
        self._max_seq_length = max_seq_length
        self._normalize = normalize
        self._num_threads = num_threads
        self._hf_hub_offline = hf_hub_offline
        self._model = None
        self._model_key = model_key

    @property
    def model_name(self) -> str:
        return self._resolve_identity()

    @property
    def model_key(self) -> str:
        if self._model_key:
            return self._model_key
        identity = self._resolve_identity()
        rev = self._model_revision or "default"
        norm = "true" if self._normalize else "false"
        return (
            f"{identity}|rev={rev}|dim={self._dimension}"
            f"|norm={norm}|maxlen={self._max_seq_length}"
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_revision(self) -> str | None:
        return self._model_revision or "default"

    @property
    def normalized(self) -> bool:
        return self._normalize

    def _resolve_identity(self) -> str:
        if self._model_path and Path(self._model_path).exists():
            return self._model_path
        return self._model_name

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        identity = self._resolve_identity()
        local_only = bool(self._model_path and Path(self._model_path).exists())

        if self._hf_hub_offline or os.getenv("HF_HUB_OFFLINE") == "1":
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
            if not local_only and not Path(identity).exists():
                raise ModelNotAvailableError(
                    "Offline mode enabled but local model path is missing or invalid"
                )

        if self._num_threads is not None:
            try:
                import torch

                torch.set_num_threads(int(self._num_threads))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to set torch num_threads: %s", type(exc).__name__)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ModelNotAvailableError(
                "sentence-transformers is not installed; cannot load BGE-M3"
            ) from exc

        load_kwargs: dict = {"device": self._device}
        if self._model_revision and not local_only:
            load_kwargs["revision"] = self._model_revision
        if local_only:
            load_kwargs["local_files_only"] = True

        try:
            logger.info("Loading embedding model identity=%s device=%s", identity, self._device)
            model = SentenceTransformer(identity, **load_kwargs)
            model.max_seq_length = self._max_seq_length
            self._model = model
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadFailedError(
                f"Failed to load embedding model: {type(exc).__name__}"
            ) from exc

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        self._ensure_model()
        assert self._model is not None

        vectors: list[list[float]] = []
        try:
            for start in range(0, len(texts), self._batch_size):
                batch = texts[start : start + self._batch_size]
                encoded = self._model.encode(
                    batch,
                    batch_size=len(batch),
                    normalize_embeddings=self._normalize,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                for row in encoded:
                    vec = [float(x) for x in row.tolist()]
                    if len(vec) != self._dimension:
                        raise DimensionMismatchError(
                            f"Expected dimension {self._dimension}, got {len(vec)}"
                        )
                    vectors.append(vec)
        except EmbeddingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingFailedError(f"Embedding failed: {type(exc).__name__}") from exc
        return vectors
