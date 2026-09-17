"""Pydantic schemas for DB analysis preflight checks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PreflightOverallStatus = Literal["READY", "WARNING", "BLOCKED"]
PreflightCheckStatus = Literal["PASS", "WARNING", "BLOCKED"]


class PreflightRequest(BaseModel):
    password: str | None = None
    schemas: list[str] = Field(default_factory=list)


class PreflightCheck(BaseModel):
    key: str
    name: str
    status: PreflightCheckStatus
    schema_name: str | None = None
    count: int | None = None
    detail: str


class PreflightConnection(BaseModel):
    dbms_product: str | None = None
    db_version: str | None = None
    database_or_service: str | None = None
    current_user: str | None = None


class PreflightSummary(BaseModel):
    passed: int
    warnings: int
    blocked: int
    tables: int
    columns: int
    primary_keys: int
    unique_constraints: int
    foreign_keys: int
    indexes: int
    table_comments: int
    column_comments: int


class PreflightSecurity(BaseModel):
    business_data_selected: bool = False
    credentials_returned: bool = False
    metadata_select_only: bool = True


class PreflightResponse(BaseModel):
    target_id: int
    source_name: str
    db_type: str
    schemas: list[str]
    status: PreflightOverallStatus
    generated_at: datetime
    connection: PreflightConnection
    summary: PreflightSummary
    checks: list[PreflightCheck]
    security: PreflightSecurity
