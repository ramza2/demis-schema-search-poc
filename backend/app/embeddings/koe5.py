"""KoE5 Embedding Provider (CPU-capable, local/offline, E5 query/passage prefixes).

Official model for this PoC:
  nlpai-lab/KoE5 (NLP&AI Lab, Korea University)
  base: intfloat/multilingual-e5-large
  license: MIT
  dimension: 1024
  max sequence length: 512

Weights are never committed to git; load from a prepared local path in offline mode.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from app.embeddings.base import EmbeddingProvider
from app.embeddings.errors import (
    ConfigurationError,
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingFailedError,
    ModelLoadFailedError,
    ModelNotAvailableError,
)

logger = logging.getLogger(__name__)

# Pinned provenance (weights NOT in git).
KOE5_REPO_ID = "nlpai-lab/KoE5"
KOE5_DEVELOPER = "NLP&AI Lab, Korea University"
KOE5_BASE_MODEL = "intfloat/multilingual-e5-large"
KOE5_LICENSE = "MIT"
KOE5_PINNED_REVISION = "bc6d284c60fe5a973e74c1751b92594c9f581213"
KOE5_SAFETENSORS_SHA256 = (
    "97693a2aeaeae9ecaac5fc68c5d27007dd1604d667ccbc61a32a52a9035cca67"
)
KOE5_DIMENSION = 1024
KOE5_MAX_SEQ_LENGTH = 512
KOE5_PREFIX_POLICY = "e5-query-passage-v1"
KOE5_QUERY_PREFIX = "query: "
KOE5_DOCUMENT_PREFIX = "passage: "


def apply_e5_prefix(text: str, prefix: str) -> str:
    """Apply an E5 prefix once; skip if text already starts with query:/passage:."""
    stripped = (text or "").lstrip()
    lower = stripped.lower()
    if lower.startswith("query:") or lower.startswith("passage:"):
        return text
    return f"{prefix}{text}"


def resolve_koe5_revision(revision: str | None) -> str:
    """Empty/blank revision always resolves to the pinned KoE5 commit SHA."""
    return (revision or "").strip() or KOE5_PINNED_REVISION


def build_koe5_model_key(
    *,
    model_name: str = KOE5_REPO_ID,
    revision: str = KOE5_PINNED_REVISION,
    dimension: int = KOE5_DIMENSION,
    normalize: bool = True,
    max_seq_length: int = KOE5_MAX_SEQ_LENGTH,
    prefix_policy: str = KOE5_PREFIX_POLICY,
) -> str:
    """Stable model_key — never includes local filesystem path."""
    rev = resolve_koe5_revision(revision)
    norm = "true" if normalize else "false"
    return (
        f"provider=koe5|model={model_name}|rev={rev}"
        f"|dim={dimension}|norm={norm}|maxlen={max_seq_length}"
        f"|prefix={prefix_policy}"
    )


class Koe5EmbeddingProvider(EmbeddingProvider):
    """
    sentence-transformers KoE5 provider for air-gapped / offline deploy.

    - prefers local EMBEDDING_MODEL_PATH
    - never silently downloads when offline or when a local path is configured
    - applies E5 ``query: `` / ``passage: `` in embed_queries / embed_documents
    """

    def __init__(
        self,
        *,
        model_name: str = KOE5_REPO_ID,
        model_path: str | None = None,
        model_revision: str | None = KOE5_PINNED_REVISION,
        device: str = "cpu",
        dimension: int = KOE5_DIMENSION,
        batch_size: int = 8,
        max_seq_length: int = KOE5_MAX_SEQ_LENGTH,
        normalize: bool = True,
        num_threads: int | None = None,
        hf_hub_offline: bool = False,
        model_key: str | None = None,
        require_local_path: bool | None = None,
    ) -> None:
        self._model_name = model_name or KOE5_REPO_ID
        self._model_path = (model_path or "").strip() or None
        self._model_revision = (model_revision or "").strip() or KOE5_PINNED_REVISION
        self._device = device or "cpu"
        self._dimension = int(dimension)
        self._batch_size = max(1, batch_size)
        self._max_seq_length = int(max_seq_length)
        self._normalize = bool(normalize)
        self._num_threads = num_threads
        self._hf_hub_offline = bool(hf_hub_offline)
        self._model = None
        self._prefix_policy = KOE5_PREFIX_POLICY
        # Offline / military deploy: require a resolvable local path.
        if require_local_path is None:
            require_local_path = self._hf_hub_offline or bool(self._model_path)
        self._require_local_path = bool(require_local_path)
        self._model_key = model_key or build_koe5_model_key(
            model_name=self._model_name,
            revision=self._model_revision,
            dimension=self._dimension,
            normalize=self._normalize,
            max_seq_length=self._max_seq_length,
            prefix_policy=self._prefix_policy,
        )

        if self._dimension != KOE5_DIMENSION:
            raise ConfigurationError(
                f"KoE5 requires dimension={KOE5_DIMENSION}, got {self._dimension}"
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

    @property
    def query_prefix(self) -> str:
        return KOE5_QUERY_PREFIX

    @property
    def document_prefix(self) -> str:
        return KOE5_DOCUMENT_PREFIX

    @property
    def prefix_policy(self) -> str:
        return self._prefix_policy

    def _local_path_ready(self) -> Path | None:
        if not self._model_path:
            return None
        path = Path(self._model_path)
        if path.is_dir() and path.exists():
            return path
        return None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return

        local = self._local_path_ready()
        offline = self._hf_hub_offline or os.getenv("HF_HUB_OFFLINE") == "1"

        if self._require_local_path or offline:
            if local is None:
                raise ConfigurationError(
                    "KoE5 offline/local mode requires a valid EMBEDDING_MODEL_PATH "
                    f"(expected local directory for {self._model_name}). "
                    "Prepare weights with scripts/prepare_koe5_model.py; "
                    "automatic Hub download is disabled."
                )

        if offline:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

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
                "sentence-transformers is not installed; cannot load KoE5"
            ) from exc

        if local is not None:
            identity = str(local)
            load_kwargs: dict = {
                "device": self._device,
                "local_files_only": True,
            }
        else:
            # Online path only when explicitly allowed (no path + not offline).
            identity = self._model_name
            load_kwargs = {
                "device": self._device,
                "revision": self._model_revision,
            }

        try:
            logger.info(
                "Loading KoE5 identity=%s device=%s revision=%s local_only=%s",
                identity,
                self._device,
                self._model_revision,
                bool(local),
            )
            model = SentenceTransformer(identity, **load_kwargs)
            model.max_seq_length = self._max_seq_length
            self._model = model
        except ConfigurationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadFailedError(
                f"Failed to load KoE5 model: {type(exc).__name__}"
            ) from exc

    def _encode(self, texts: list[str]) -> list[list[float]]:
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
            raise EmbeddingFailedError(
                f"KoE5 embedding failed: {type(exc).__name__}"
            ) from exc
        return vectors

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Raw encode without adding E5 prefixes (prefer embed_queries / embed_documents)."""
        return self._encode(texts)

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        prefixed = [apply_e5_prefix(t, KOE5_QUERY_PREFIX) for t in texts]
        return self._encode(prefixed)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed = [apply_e5_prefix(t, KOE5_DOCUMENT_PREFIX) for t in texts]
        return self._encode(prefixed)
