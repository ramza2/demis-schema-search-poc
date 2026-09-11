"""Search API request/response schemas (Step 4)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SchemaSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    mode: Literal["semantic", "keyword", "hybrid"] = "hybrid"
    top_k: int = Field(default=10, ge=1, le=50)
    object_type: Literal["ALL", "TABLE", "COLUMN"] = "ALL"
    expand_terms: bool = True
    expand_relations: bool = True
    max_relation_hops: int = Field(default=2, ge=0, le=4)
    debug: bool = False


class QueryInfo(BaseModel):
    original: str
    normalized: str
    expanded: str
    matched_concepts: list[str] = Field(default_factory=list)
    expanded_terms: list[str] = Field(default_factory=list)


class RelationHopOut(BaseModel):
    from_table: str
    to_table: str
    constraint_name: str
    direction: str
    from_columns: list[str] = Field(default_factory=list)
    to_columns: list[str] = Field(default_factory=list)


class DirectResultOut(BaseModel):
    rank: int
    match_type: str = "DIRECT"
    object_type: str
    table_name: str | None = None
    column_name: str | None = None
    document_key: str
    document_id: int
    semantic_score: float | None = None
    semantic_rank: int | None = None
    keyword_score: float | None = None
    keyword_rank: int | None = None
    rrf_score: float | None = None
    evidence: list[str] = Field(default_factory=list)
    searchable_snippet: str | None = None


class RelatedTableOut(BaseModel):
    table_name: str
    schema_name: str
    seed_table: str
    hop_distance: int
    match_type: str = "RELATED"
    relation_path: list[RelationHopOut] = Field(default_factory=list)


class SchemaSearchResponse(BaseModel):
    query: QueryInfo
    mode: str
    model_key: str | None = None
    object_type: str
    direct_results: list[DirectResultOut] = Field(default_factory=list)
    related_tables: list[RelatedTableOut] = Field(default_factory=list)
    elapsed_ms: float
    timings: dict[str, float] = Field(default_factory=dict)
    debug: dict[str, Any] | None = None
