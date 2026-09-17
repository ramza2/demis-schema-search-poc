"""Catalog business-category ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.catalog import CatalogBase


class CatalogCategory(CatalogBase):
    """Source-scoped business category used to organize analyzed tables."""

    __tablename__ = "catalog_category"
    __table_args__ = (
        UniqueConstraint("source_id", "category_key", name="uq_catalog_category_source_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_source.id", ondelete="CASCADE"), nullable=False
    )
    category_key: Mapped[str] = mapped_column(String(100), nullable=False)
    category_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    table_mappings: Mapped[list[CatalogTableCategory]] = relationship(
        back_populates="category", cascade="all, delete-orphan", passive_deletes=True
    )


class CatalogTableCategory(CatalogBase):
    """Many-to-many mapping between catalog tables and business categories."""

    __tablename__ = "catalog_table_category"
    __table_args__ = (
        UniqueConstraint("table_id", "category_id", name="uq_catalog_table_category"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)",
            name="ck_catalog_table_category_confidence",
        ),
        CheckConstraint(
            "assignment_source IN ('MANUAL', 'AUTO', 'IMPORT')",
            name="ck_catalog_table_category_assignment_source",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_table.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_category.id", ondelete="CASCADE"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assignment_source: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    confidence: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    category: Mapped[CatalogCategory] = relationship(back_populates="table_mappings")
