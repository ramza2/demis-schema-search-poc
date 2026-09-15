"""Pydantic schemas for Target management APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.target_connection import validate_target_host
from app.schemas.schema_api import AnalyzeResponse


class TargetCreate(BaseModel):
    source_name: str = Field(min_length=1, max_length=100)
    db_type: str = Field(min_length=1, max_length=40)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=100)
    default_schema: str = Field(default="public", min_length=1, max_length=100)
    username: str = Field(min_length=1, max_length=255)
    # Plaintext only in request; empty string is a valid passwordless credential.
    password: str
    connection_options: dict[str, Any] | None = None
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        return validate_target_host(value)


class TargetUpdate(BaseModel):
    source_name: str | None = Field(default=None, min_length=1, max_length=100)
    db_type: str | None = Field(default=None, min_length=1, max_length=40)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, min_length=1, max_length=100)
    default_schema: str | None = Field(default=None, min_length=1, max_length=100)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    # Omit / null -> keep existing credential. Empty string -> replace with passwordless credential.
    password: str | None = None
    clear_saved_password: bool = False
    connection_options: dict[str, Any] | None = None
    enabled: bool | None = None

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_target_host(value)

    @model_validator(mode="after")
    def _password_vs_clear(self) -> TargetUpdate:
        password_was_set = "password" in self.model_fields_set and self.password is not None
        if self.clear_saved_password and password_was_set:
            raise ValueError("password and clear_saved_password cannot both be set")
        return self


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_name: str
    db_type: str
    host: str | None = None
    port: int | None = None
    database_name: str
    default_schema: str
    username: str | None = None
    connection_options: dict[str, Any] | None = None
    enabled: bool
    has_saved_password: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PasswordRequest(BaseModel):
    """Optional password for Test/Discover. Uses saved credential when omitted."""

    password: str | None = None


class AnalyzeRequest(BaseModel):
    password: str | None = None
    schemas: list[str] = Field(min_length=1)


class TestConnectionResponse(BaseModel):
    connected: bool
    dbms_product: str
    db_version: str
    database_or_service: str
    current_user: str


class SchemaListResponse(BaseModel):
    schemas: list[str]


TargetAnalyzeResponse = AnalyzeResponse


class CatalogSummaryResponse(BaseModel):
    source_id: int
    source_name: str
    tables: int
    columns: int
    relations: int
    indexes: int
    last_success_run_id: int | None = None
    last_success_fingerprint: str | None = None
    last_success_at: datetime | None = None
