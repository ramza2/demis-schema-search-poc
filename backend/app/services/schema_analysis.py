"""Schema analysis orchestration service."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analyzers.factory import create_schema_inspector
from app.core.config import Settings, get_settings
from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory, get_medical_engine
from app.db.target_connection import mask_secrets
from app.models.catalog import CatalogAnalysisRun, CatalogSource
from app.services.catalog_writer import CatalogWriter, schema_snapshot_fingerprint

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_message(
    exc: Exception,
    settings: Settings,
    *extra_secrets: str | None,
) -> str:
    """Strip credentials from exception text before persistence/logging."""
    message = f"{type(exc).__name__}: {exc}"
    secrets = (
        settings.medical_db_password,
        settings.catalog_db_password,
        *extra_secrets,
    )
    message = mask_secrets(message, *secrets)
    if "://" in message and "@" in message:
        message = "Analysis failed (details redacted to avoid credential leakage)"
    return message[:2000]


class SchemaAnalysisService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def analyze_medical_demo(self, schema_name: str = "public") -> CatalogAnalysisRun:
        """Backward-compatible medical_demo analysis using settings password."""
        ensure_catalog_schema(self.settings)
        factory = get_catalog_session_factory(self.settings)
        session: Session = factory()
        run: CatalogAnalysisRun | None = None
        try:
            source = session.scalar(
                select(CatalogSource).where(
                    CatalogSource.source_name == "medical_demo",
                    CatalogSource.enabled.is_(True),
                )
            )
            if source is None:
                raise RuntimeError("catalog_source 'medical_demo' is not registered")

            run = CatalogAnalysisRun(
                source_id=source.id,
                status="RUNNING",
                target_schema=schema_name,
                started_at=_utcnow(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            engine = get_medical_engine(self.settings)
            inspector = create_schema_inspector(
                source.db_type or "postgresql",
                engine,
                source.database_name or self.settings.medical_db_name,
            )
            snapshot = inspector.inspect(schema_name=schema_name)
            schema_fp = schema_snapshot_fingerprint(snapshot)

            writer = CatalogWriter(session)
            writer.upsert_snapshot(
                source_id=source.id,
                run_id=run.id,
                snapshot=snapshot,
                analyzed_schemas={schema_name},
            )

            run.status = "SUCCESS"
            run.finished_at = _utcnow()
            run.table_count = len(snapshot.tables)
            run.column_count = len(snapshot.columns)
            run.relation_count = len(snapshot.foreign_keys)
            run.index_count = len(snapshot.indexes)
            run.schema_fingerprint = schema_fp
            run.error_message = None
            session.commit()
            session.refresh(run)
            logger.info(
                "Schema analysis SUCCESS source=medical_demo schema=%s tables=%s columns=%s relations=%s indexes=%s",
                schema_name,
                run.table_count,
                run.column_count,
                run.relation_count,
                run.index_count,
            )
            return run
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            safe_msg = _safe_error_message(
                exc, self.settings, self.settings.medical_db_password
            )
            logger.exception("Schema analysis FAILED: %s", safe_msg)
            if run is not None and run.id is not None:
                failed = session.get(CatalogAnalysisRun, run.id)
                if failed is not None:
                    failed.status = "FAILED"
                    failed.finished_at = _utcnow()
                    failed.error_message = safe_msg
                    session.commit()
                    session.refresh(failed)
                    return failed
            source = session.scalar(
                select(CatalogSource).where(CatalogSource.source_name == "medical_demo")
            )
            if source is not None:
                failed_run = CatalogAnalysisRun(
                    source_id=source.id,
                    status="FAILED",
                    target_schema=schema_name,
                    started_at=_utcnow(),
                    finished_at=_utcnow(),
                    error_message=safe_msg,
                )
                session.add(failed_run)
                session.commit()
                session.refresh(failed_run)
                return failed_run
            raise
        finally:
            session.close()
