"""API models for persisted analysis snapshots and schema-run diffs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SchemaRunRef(BaseModel):
    run_id: int
    status: str
    target_schema: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    table_count: int = 0
    column_count: int = 0
    relation_count: int = 0
    index_count: int = 0
    schema_fingerprint: str | None = None
    snapshot_available: bool = False
    snapshot_created_at: datetime | None = None
    capture_mode: str | None = None


class SchemaRunListResponse(BaseModel):
    source_id: int
    source_name: str
    runs: list[SchemaRunRef] = Field(default_factory=list)


class SnapshotCaptureResponse(BaseModel):
    source_id: int
    source_name: str
    run_id: int
    created: bool
    capture_mode: str
    snapshot_version: str
    created_at: datetime | None = None


class DiffCount(BaseModel):
    added: int = 0
    removed: int = 0
    changed: int = 0

    @property
    def total(self) -> int:
        return self.added + self.removed + self.changed


class SchemaDiffSummary(BaseModel):
    tables: DiffCount = Field(default_factory=DiffCount)
    columns: DiffCount = Field(default_factory=DiffCount)
    key_constraints: DiffCount = Field(default_factory=DiffCount)
    foreign_keys: DiffCount = Field(default_factory=DiffCount)
    indexes: DiffCount = Field(default_factory=DiffCount)
    total_changes: int = 0


class SchemaDiffChange(BaseModel):
    object_type: Literal["TABLE", "COLUMN", "KEY_CONSTRAINT", "FOREIGN_KEY", "INDEX"]
    change_type: Literal["ADDED", "REMOVED", "CHANGED"]
    object_key: str
    changed_fields: list[str] = Field(default_factory=list)
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class SchemaDiffResponse(BaseModel):
    source_id: int
    source_name: str
    base_run: SchemaRunRef
    target_run: SchemaRunRef
    identical: bool
    summary: SchemaDiffSummary
    changes: list[SchemaDiffChange] = Field(default_factory=list)
