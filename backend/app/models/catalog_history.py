"""Append-only schema snapshots used for analysis-run comparisons."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.catalog import CatalogBase


class CatalogAnalysisSnapshot(CatalogBase):
    """Physical schema snapshot captured for one successful analysis run."""

    __tablename__ = "catalog_analysis_snapshot"
    __table_args__ = (UniqueConstraint("run_id", name="uq_catalog_analysis_snapshot_run"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_source.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("catalog_analysis_run.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    capture_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="ANALYSIS_API")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
