"""Pydantic schemas for Schema Analyzer APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: int
    status: str
    source: str
    schema_name: str = Field(serialization_alias="schema")
    tables: int
    columns: int
    relations: int
    indexes: int
    schema_fingerprint: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


class AnalysisRunSummary(BaseModel):
    id: int
    source_id: int
    status: str
    target_schema: str
    started_at: datetime | None
    finished_at: datetime | None
    table_count: int
    column_count: int
    relation_count: int
    index_count: int
    schema_fingerprint: str | None = None
    error_message: str | None = None


class ColumnOut(BaseModel):
    id: int
    column_name: str
    ordinal_position: int
    data_type: str
    character_maximum_length: int | None = None
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    nullable: bool
    default_value: str | None = None
    comment: str | None = None
    primary_key: bool
    unique: bool
    object_fingerprint: str


class RelationColumnMapping(BaseModel):
    source: str
    target: str
    ordinal_position: int


class RelationOut(BaseModel):
    id: int
    constraint: str
    relation_type: str
    source_table: str
    target_table: str
    column_mapping: list[RelationColumnMapping]
    object_fingerprint: str


class IndexOut(BaseModel):
    id: int
    index_name: str
    is_unique: bool
    index_method: str | None = None
    index_definition: str | None = None
    columns: list[str]
    object_fingerprint: str


class TableSummary(BaseModel):
    id: int
    schema_name: str
    table_name: str
    table_type: str
    table_comment: str | None = None
    active: bool
    object_fingerprint: str
    column_count: int = 0


class TableDetail(BaseModel):
    id: int
    schema_name: str
    table_name: str
    table_type: str
    table_comment: str | None = None
    object_fingerprint: str
    active: bool
    columns: list[ColumnOut]
    outbound_relations: list[RelationOut]
    inbound_relations: list[RelationOut]
    indexes: list[IndexOut]
