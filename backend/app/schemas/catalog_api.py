"""Pydantic schemas for Catalog Category APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


CATEGORY_KEY_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,99}$"
ASSIGNMENT_SOURCE_PATTERN = r"^(MANUAL|AUTO|IMPORT)$"


class CategoryCreate(BaseModel):
    source_id: int = Field(gt=0)
    category_key: str = Field(min_length=1, max_length=100, pattern=CATEGORY_KEY_PATTERN)
    category_name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    sort_order: int = 0
    active: bool = True


class CategoryUpdate(BaseModel):
    category_name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    sort_order: int | None = None
    active: bool | None = None


class CategoryOut(BaseModel):
    id: int
    source_id: int
    category_key: str
    category_name: str
    description: str | None = None
    sort_order: int
    active: bool
    table_count: int = 0


class CategoryTableOut(BaseModel):
    table_id: int
    schema_name: str
    table_name: str
    table_comment: str | None = None
    is_primary: bool
    assignment_source: str
    confidence: float | None = None


class TableCategoryAssignment(BaseModel):
    category_id: int = Field(gt=0)
    is_primary: bool = False
    assignment_source: str = Field(default="MANUAL", pattern=ASSIGNMENT_SOURCE_PATTERN)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    note: str | None = None


class TableCategoryReplace(BaseModel):
    assignments: list[TableCategoryAssignment] = Field(default_factory=list)


class TableCategoryOut(BaseModel):
    category_id: int
    category_key: str
    category_name: str
    is_primary: bool
    assignment_source: str
    confidence: float | None = None
    note: str | None = None
