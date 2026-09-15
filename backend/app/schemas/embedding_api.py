"""Pydantic schemas for embedding / search-document APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentRebuildResponse(BaseModel):
    source: str
    tables: int
    columns: int
    documents: int
    created: int
    updated: int
    unchanged: int
    deactivated: int = 0


class EmbeddingRunResponse(BaseModel):
    run_id: int
    status: str
    model_key: str
    documents: int
    embedded: int
    skipped: int
    failed: int
    started_at: datetime
    finished_at: datetime | None = None
    error_message: str | None = None
    error_code: str | None = None


class EmbeddingRunSummary(BaseModel):
    id: int
    source_id: int
    status: str
    model_key: str
    started_at: datetime
    finished_at: datetime | None = None
    document_count: int
    embedded_count: int
    skipped_count: int
    failed_count: int
    error_message: str | None = None
    error_code: str | None = None


class EmbeddingStatsResponse(BaseModel):
    active_documents: int
    table_documents: int
    column_documents: int
    embedding_count: int
    model_keys: list[str] = Field(default_factory=list)
    stale_documents: int
    embedding_provider: str
    embedding_device: str
    embedding_dimension: int
    source_id: int | None = None
    source_name: str | None = None


class SearchDocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    object_type: str
    table_id: int | None
    column_id: int | None
    document_key: str
    document_fingerprint: str
    source_fingerprint: str
    builder_version: str
    active: bool
    has_embedding: bool = False
    model_key: str | None = None


class SearchDocumentDetail(SearchDocumentSummary):
    searchable_text: str
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
    embedding_dimension: int | None = None
    model_name: str | None = None
    model_revision: str | None = None
    normalized: bool | None = None
