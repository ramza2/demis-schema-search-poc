"""Catalog ORM models (schema_catalog DB)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class CatalogBase(DeclarativeBase):
    pass


class CatalogSource(CatalogBase):
    __tablename__ = "catalog_source"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    db_type: Mapped[str] = mapped_column(String(40), nullable=False)
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int | None] = mapped_column(Integer)
    database_name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_schema: Mapped[str] = mapped_column(String(100), nullable=False, default="public")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CatalogAnalysisRun(CatalogBase):
    __tablename__ = "catalog_analysis_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("catalog_source.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    target_schema: Mapped[str] = mapped_column(String(100), nullable=False, default="public")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CatalogTable(CatalogBase):
    __tablename__ = "catalog_table"
    __table_args__ = (UniqueConstraint("source_id", "schema_name", "table_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("catalog_source.id"), nullable=False)
    schema_name: Mapped[str] = mapped_column(String(100), nullable=False)
    table_name: Mapped[str] = mapped_column(String(200), nullable=False)
    table_type: Mapped[str] = mapped_column(String(50), nullable=False, default="BASE TABLE")
    table_comment: Mapped[str | None] = mapped_column(Text)
    object_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("catalog_analysis_run.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    columns: Mapped[list[CatalogColumn]] = relationship(back_populates="table", cascade="all, delete-orphan")
    indexes: Mapped[list[CatalogIndex]] = relationship(back_populates="table", cascade="all, delete-orphan")


class CatalogColumn(CatalogBase):
    __tablename__ = "catalog_column"
    __table_args__ = (UniqueConstraint("table_id", "column_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("catalog_table.id", ondelete="CASCADE"))
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_type: Mapped[str] = mapped_column(String(100), nullable=False)
    character_maximum_length: Mapped[int | None] = mapped_column(Integer)
    numeric_precision: Mapped[int | None] = mapped_column(Integer)
    numeric_scale: Mapped[int | None] = mapped_column(Integer)
    is_nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_value: Mapped[str | None] = mapped_column(Text)
    column_comment: Mapped[str | None] = mapped_column(Text)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    object_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("catalog_analysis_run.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    table: Mapped[CatalogTable] = relationship(back_populates="columns")


class CatalogRelation(CatalogBase):
    __tablename__ = "catalog_relation"
    __table_args__ = (UniqueConstraint("source_id", "constraint_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("catalog_source.id"), nullable=False)
    constraint_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_table.id", ondelete="CASCADE"), nullable=False
    )
    target_table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_table.id", ondelete="CASCADE"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(40), nullable=False, default="FOREIGN_KEY")
    object_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("catalog_analysis_run.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    columns: Mapped[list[CatalogRelationColumn]] = relationship(
        back_populates="relation", cascade="all, delete-orphan"
    )


class CatalogRelationColumn(CatalogBase):
    __tablename__ = "catalog_relation_column"
    __table_args__ = (UniqueConstraint("relation_id", "ordinal_position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    relation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_relation.id", ondelete="CASCADE"), nullable=False
    )
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    source_column_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_column.id", ondelete="CASCADE"), nullable=False
    )
    target_column_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_column.id", ondelete="CASCADE"), nullable=False
    )

    relation: Mapped[CatalogRelation] = relationship(back_populates="columns")


class CatalogIndex(CatalogBase):
    __tablename__ = "catalog_index"
    __table_args__ = (UniqueConstraint("table_id", "index_name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_table.id", ondelete="CASCADE"), nullable=False
    )
    index_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_unique: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    index_method: Mapped[str | None] = mapped_column(String(50))
    index_definition: Mapped[str | None] = mapped_column(Text)
    object_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("catalog_analysis_run.id"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    table: Mapped[CatalogTable] = relationship(back_populates="indexes")
    columns: Mapped[list[CatalogIndexColumn]] = relationship(
        back_populates="index", cascade="all, delete-orphan"
    )


class CatalogIndexColumn(CatalogBase):
    __tablename__ = "catalog_index_column"
    __table_args__ = (UniqueConstraint("index_id", "ordinal_position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    index_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_index.id", ondelete="CASCADE"), nullable=False
    )
    ordinal_position: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str] = mapped_column(String(200), nullable=False)

    index: Mapped[CatalogIndex] = relationship(back_populates="columns")
