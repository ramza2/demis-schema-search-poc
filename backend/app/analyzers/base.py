"""Schema inspector abstractions and DTOs (DBMS-agnostic)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InspectedColumn:
    schema_name: str
    table_name: str
    ordinal_position: int
    column_name: str
    data_type: str
    character_maximum_length: int | None
    numeric_precision: int | None
    numeric_scale: int | None
    is_nullable: bool
    default_value: str | None
    column_comment: str | None


@dataclass(frozen=True)
class InspectedTable:
    schema_name: str
    table_name: str
    table_type: str
    table_comment: str | None


@dataclass(frozen=True)
class InspectedPrimaryKey:
    schema_name: str
    table_name: str
    constraint_name: str
    column_name: str
    ordinal_position: int


@dataclass(frozen=True)
class InspectedUniqueConstraint:
    schema_name: str
    table_name: str
    constraint_name: str
    column_name: str
    ordinal_position: int


@dataclass(frozen=True)
class InspectedForeignKeyColumn:
    ordinal_position: int
    source_column: str
    target_column: str


@dataclass(frozen=True)
class InspectedForeignKey:
    schema_name: str
    constraint_name: str
    source_table: str
    target_schema: str
    target_table: str
    columns: tuple[InspectedForeignKeyColumn, ...]


@dataclass(frozen=True)
class InspectedIndexColumn:
    ordinal_position: int
    column_name: str


@dataclass(frozen=True)
class InspectedIndex:
    schema_name: str
    table_name: str
    index_name: str
    is_unique: bool
    index_method: str | None
    index_definition: str | None
    columns: tuple[InspectedIndexColumn, ...]


@dataclass
class SchemaSnapshot:
    db_type: str
    database_name: str
    schema_name: str
    tables: list[InspectedTable] = field(default_factory=list)
    columns: list[InspectedColumn] = field(default_factory=list)
    primary_keys: list[InspectedPrimaryKey] = field(default_factory=list)
    unique_constraints: list[InspectedUniqueConstraint] = field(default_factory=list)
    foreign_keys: list[InspectedForeignKey] = field(default_factory=list)
    indexes: list[InspectedIndex] = field(default_factory=list)


class SchemaInspector(ABC):
    """Interface for DBMS-specific schema metadata collection (read-only)."""

    @abstractmethod
    def inspect(self, schema_name: str = "public") -> SchemaSnapshot:
        raise NotImplementedError
