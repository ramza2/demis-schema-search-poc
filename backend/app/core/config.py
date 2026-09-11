"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _empty_as_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DEMIS Schema Semantic Search PoC"
    current_step: str = "Step 4 - Semantic/Keyword Hybrid Search + Terminology + FK Expansion"
    log_level: str = "INFO"

    medical_db_host: str = "localhost"
    medical_db_port: int = 5432
    medical_db_name: str = "medical_demo"
    medical_db_user: str = "medical_user"
    medical_db_password: str = "medical_pass_change_me"

    catalog_db_host: str = "localhost"
    catalog_db_port: int = 5432
    catalog_db_name: str = "schema_catalog"
    catalog_db_user: str = "catalog_user"
    catalog_db_password: str = "catalog_pass_change_me"

    # Embedding (Step 3) — CPU-only by default; no generative LLM.
    embedding_provider: str = "bge_m3"  # bge_m3 | fake
    embedding_model_name: str = "BAAI/bge-m3"
    embedding_model_path: str | None = None
    embedding_model_revision: str | None = None
    embedding_device: str = "cpu"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 8
    embedding_max_seq_length: int = 1024
    embedding_normalize: bool = True
    embedding_num_threads: int | None = None
    hf_hub_offline: bool = False

    # Step 4 search settings
    allow_fake_semantic_search: bool = False
    search_rrf_k: int = 60
    search_candidate_multiplier: int = 3
    search_candidate_min: int = 20
    medical_terms_path: str | None = None

    @field_validator(
        "embedding_model_path",
        "embedding_model_revision",
        "embedding_num_threads",
        "medical_terms_path",
        mode="before",
    )
    @classmethod
    def _optional_empty_to_none(cls, value: Any) -> Any:
        return _empty_as_none(value)

    @property
    def medical_db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.medical_db_user}:{self.medical_db_password}"
            f"@{self.medical_db_host}:{self.medical_db_port}/{self.medical_db_name}"
        )

    @property
    def catalog_db_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.catalog_db_user}:{self.catalog_db_password}"
            f"@{self.catalog_db_host}:{self.catalog_db_port}/{self.catalog_db_name}"
        )

    def resolved_load_path(self) -> str:
        """Where to load model weights from (local path preferred when present)."""
        path = (self.embedding_model_path or "").strip()
        if path and Path(path).exists():
            return path
        return self.embedding_model_name

    def resolved_model_identity(self) -> str:
        """
        Logical model identity used in model_key.

        Path is intentionally excluded so the same BGE-M3 weights at different
        local directories share one model_key with document embeddings.
        """
        return self.embedding_model_name

    # Backward-compatible alias used by older call sites.
    def resolved_model_load_identity(self) -> str:
        return self.resolved_load_path()

    def build_model_key(self) -> str:
        identity = self.resolved_model_identity()
        rev = self.embedding_model_revision or "default"
        norm = "true" if self.embedding_normalize else "false"
        return (
            f"{identity}|rev={rev}|dim={self.embedding_dimension}"
            f"|norm={norm}|maxlen={self.embedding_max_seq_length}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
