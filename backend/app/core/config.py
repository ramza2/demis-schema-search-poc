"""Application settings loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "DEMIS Schema Semantic Search PoC"
    current_step: str = "Step 2 - Schema Analyzer / Schema Catalog"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
