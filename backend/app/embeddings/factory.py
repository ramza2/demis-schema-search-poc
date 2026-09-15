"""Factory for embedding providers."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.errors import ConfigurationError
from app.embeddings.fake import FakeEmbeddingProvider


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    cfg = settings or get_settings()
    provider = (cfg.embedding_provider or "").strip().lower()
    if not provider:
        raise ConfigurationError("EMBEDDING_PROVIDER is empty")

    if provider == "fake":
        return FakeEmbeddingProvider(
            dimension=cfg.embedding_dimension,
            normalize=cfg.embedding_normalize,
            model_name="fake-embedding",
            model_key=(
                f"fake-embedding|rev=default|dim={cfg.embedding_dimension}"
                f"|norm={'true' if cfg.embedding_normalize else 'false'}"
                f"|maxlen={cfg.embedding_max_seq_length}"
            ),
            max_seq_length=cfg.embedding_max_seq_length,
        )

    if provider == "openai_compatible":
        from app.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider

        return OpenAICompatibleEmbeddingProvider(
            api_url=cfg.embedding_api_url or "",
            api_key=cfg.embedding_api_key,
            timeout_seconds=cfg.embedding_api_timeout_seconds,
            model_name=cfg.embedding_model_name,
            dimension=cfg.embedding_dimension,
            normalize=cfg.embedding_normalize,
            max_seq_length=cfg.embedding_max_seq_length,
            model_revision=cfg.embedding_model_revision,
        )

    if provider == "bge_m3":
        # Lazy import so health / non-embedding paths do not require torch.
        from app.embeddings.bge_m3 import BgeM3EmbeddingProvider

        return BgeM3EmbeddingProvider(
            model_name=cfg.embedding_model_name,
            model_path=cfg.embedding_model_path,
            model_revision=cfg.embedding_model_revision,
            device=cfg.embedding_device,
            dimension=cfg.embedding_dimension,
            batch_size=cfg.embedding_batch_size,
            max_seq_length=cfg.embedding_max_seq_length,
            normalize=cfg.embedding_normalize,
            num_threads=cfg.embedding_num_threads,
            hf_hub_offline=cfg.hf_hub_offline,
            model_key=cfg.build_model_key(),
        )

    if provider == "koe5":
        from app.embeddings.koe5 import Koe5EmbeddingProvider

        return Koe5EmbeddingProvider(
            model_name=cfg.embedding_model_name,
            model_path=cfg.embedding_model_path,
            model_revision=cfg.embedding_model_revision,
            device=cfg.embedding_device,
            dimension=cfg.embedding_dimension,
            batch_size=cfg.embedding_batch_size,
            max_seq_length=cfg.embedding_max_seq_length,
            normalize=cfg.embedding_normalize,
            num_threads=cfg.embedding_num_threads,
            hf_hub_offline=cfg.hf_hub_offline,
            model_key=cfg.build_model_key(),
        )

    raise ConfigurationError(
        f"Unknown EMBEDDING_PROVIDER={provider!r}. "
        "Supported values: fake, bge_m3, openai_compatible, koe5"
    )


@lru_cache(maxsize=1)
def get_runtime_embedding_provider() -> EmbeddingProvider:
    """Process-lifetime cached provider for the global runtime settings.

    Uses ``get_settings()`` (also process-cached) so the heavy SentenceTransformer
    load for providers like KoE5 happens once per backend process. Do not pass a
    ``Settings`` instance as an ``lru_cache`` key — call ``get_embedding_provider``
    directly when a specific settings object is required (tests / one-off jobs).
    """
    return get_embedding_provider(get_settings())


def clear_runtime_embedding_provider_cache() -> None:
    """Drop the runtime provider cache (tests / settings reload)."""
    get_runtime_embedding_provider.cache_clear()

