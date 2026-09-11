"""Target (catalog_source) management and generalized schema analysis."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analyzers.base import merge_snapshots
from app.analyzers.factory import create_schema_inspector
from app.core.config import Settings, get_settings
from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.db.target_connection import (
    DEFAULT_PORTS,
    TargetConnectionInfo,
    create_target_engine,
    mask_secrets,
    normalize_db_type,
    probe_connection,
)
from app.models.catalog import (
    CatalogAnalysisRun,
    CatalogColumn,
    CatalogIndex,
    CatalogRelation,
    CatalogSource,
    CatalogTable,
)
from app.schemas.target_api import TargetCreate, TargetUpdate
from app.services.catalog_writer import CatalogWriter, schema_snapshot_fingerprint

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_message(exc: Exception, *secrets: str | None, settings: Settings | None = None) -> str:
    """Strip credentials from exception text before persistence/logging."""
    cfg = settings or get_settings()
    message = f"{type(exc).__name__}: {exc}"
    candidates = list(secrets) + [cfg.medical_db_password, cfg.catalog_db_password]
    message = mask_secrets(message, *candidates)
    if "://" in message and "@" in message:
        message = "Analysis failed (details redacted to avoid credential leakage)"
    return message[:2000]


def _source_to_connection_info(source: CatalogSource) -> TargetConnectionInfo:
    db_type = normalize_db_type(source.db_type)
    port = int(source.port or DEFAULT_PORTS[db_type])
    return TargetConnectionInfo(
        db_type=db_type,
        host=source.host or "localhost",
        port=port,
        database_name=source.database_name,
        username=source.username or "",
        connection_options=source.connection_options,
    )


class TargetService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _session(self) -> Session:
        ensure_catalog_schema(self.settings)
        return get_catalog_session_factory(self.settings)()

    def list_targets(self) -> list[CatalogSource]:
        session = self._session()
        try:
            rows = list(
                session.scalars(select(CatalogSource).order_by(CatalogSource.id.asc())).all()
            )
            for row in rows:
                session.expunge(row)
            return rows
        finally:
            session.close()

    def get_target(self, target_id: int) -> CatalogSource:
        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            session.expunge(source)
            return source
        finally:
            session.close()

    def create_target(self, payload: TargetCreate) -> CatalogSource:
        session = self._session()
        try:
            db_type = normalize_db_type(payload.db_type)
            source = CatalogSource(
                source_name=payload.source_name.strip(),
                db_type=db_type,
                host=payload.host.strip(),
                port=int(payload.port),
                database_name=payload.database_name.strip(),
                default_schema=payload.default_schema.strip() or "public",
                username=payload.username.strip(),
                connection_options=payload.connection_options,
                enabled=payload.enabled,
            )
            session.add(source)
            session.commit()
            session.refresh(source)
            session.expunge(source)
            return source
        except IntegrityError as exc:
            session.rollback()
            raise ValueError(f"target source_name already exists: {payload.source_name}") from exc
        finally:
            session.close()

    def update_target(self, target_id: int, payload: TargetUpdate) -> CatalogSource:
        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")

            data = payload.model_dump(exclude_unset=True)
            if "db_type" in data and data["db_type"] is not None:
                data["db_type"] = normalize_db_type(data["db_type"])
            for key, value in data.items():
                if isinstance(value, str):
                    value = value.strip()
                setattr(source, key, value)

            session.commit()
            session.refresh(source)
            session.expunge(source)
            return source
        except IntegrityError as exc:
            session.rollback()
            raise ValueError("target source_name already exists") from exc
        finally:
            session.close()

    def test_connection(self, target_id: int, password: str) -> dict[str, Any]:
        session = self._session()
        engine = None
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            info = _source_to_connection_info(source)
            engine = create_target_engine(info, password)
            return probe_connection(engine, info.db_type)
        except LookupError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(_safe_error_message(exc, password, settings=self.settings)) from exc
        finally:
            if engine is not None:
                engine.dispose()
            session.close()

    def list_schemas(self, target_id: int, password: str) -> list[str]:
        session = self._session()
        engine = None
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            info = _source_to_connection_info(source)
            engine = create_target_engine(info, password)
            inspector = create_schema_inspector(info.db_type, engine, info.database_name)
            return inspector.list_schemas()
        except LookupError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(_safe_error_message(exc, password, settings=self.settings)) from exc
        finally:
            if engine is not None:
                engine.dispose()
            session.close()

    def analyze_target(
        self,
        target_id: int,
        password: str,
        schemas: list[str],
    ) -> CatalogAnalysisRun:
        schema_list = [s.strip() for s in schemas if s and s.strip()]
        if not schema_list:
            raise ValueError("at least one schema is required")

        ensure_catalog_schema(self.settings)
        factory = get_catalog_session_factory(self.settings)
        session: Session = factory()
        run: CatalogAnalysisRun | None = None
        engine = None
        target_schema = ",".join(sorted(set(schema_list)))[:100]

        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")
            if not source.enabled:
                raise ValueError(f"target is disabled: {source.source_name}")

            run = CatalogAnalysisRun(
                source_id=source.id,
                status="RUNNING",
                target_schema=target_schema,
                started_at=_utcnow(),
            )
            session.add(run)
            session.commit()
            session.refresh(run)

            info = _source_to_connection_info(source)
            engine = create_target_engine(info, password)
            inspector = create_schema_inspector(info.db_type, engine, info.database_name)

            snapshots = [inspector.inspect(schema_name=s) for s in schema_list]
            snapshot = merge_snapshots(snapshots) if len(snapshots) > 1 else snapshots[0]
            schema_fp = schema_snapshot_fingerprint(snapshot)

            writer = CatalogWriter(session)
            writer.upsert_snapshot(
                source_id=source.id,
                run_id=run.id,
                snapshot=snapshot,
                analyzed_schemas=set(schema_list),
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
                "Schema analysis SUCCESS source=%s schemas=%s tables=%s columns=%s relations=%s indexes=%s",
                source.source_name,
                target_schema,
                run.table_count,
                run.column_count,
                run.relation_count,
                run.index_count,
            )
            session.expunge(run)
            return run
        except LookupError:
            session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            safe_msg = _safe_error_message(exc, password, settings=self.settings)
            logger.exception("Target schema analysis FAILED: %s", safe_msg)
            if run is not None and run.id is not None:
                failed = session.get(CatalogAnalysisRun, run.id)
                if failed is not None:
                    failed.status = "FAILED"
                    failed.finished_at = _utcnow()
                    failed.error_message = safe_msg
                    session.commit()
                    session.refresh(failed)
                    session.expunge(failed)
                    return failed
            source = session.get(CatalogSource, target_id)
            if source is not None:
                failed_run = CatalogAnalysisRun(
                    source_id=source.id,
                    status="FAILED",
                    target_schema=target_schema,
                    started_at=_utcnow(),
                    finished_at=_utcnow(),
                    error_message=safe_msg,
                )
                session.add(failed_run)
                session.commit()
                session.refresh(failed_run)
                session.expunge(failed_run)
                return failed_run
            raise RuntimeError(safe_msg) from exc
        finally:
            if engine is not None:
                engine.dispose()
            session.close()

    def catalog_summary(self, target_id: int) -> dict[str, Any]:
        session = self._session()
        try:
            source = session.get(CatalogSource, target_id)
            if source is None:
                raise LookupError(f"target not found: {target_id}")

            table_ids = select(CatalogTable.id).where(
                CatalogTable.source_id == target_id,
                CatalogTable.active.is_(True),
            )
            tables = session.scalar(
                select(func.count()).select_from(CatalogTable).where(
                    CatalogTable.source_id == target_id,
                    CatalogTable.active.is_(True),
                )
            )
            columns = session.scalar(
                select(func.count()).select_from(CatalogColumn).where(
                    CatalogColumn.table_id.in_(table_ids),
                    CatalogColumn.active.is_(True),
                )
            )
            relations = session.scalar(
                select(func.count()).select_from(CatalogRelation).where(
                    CatalogRelation.source_id == target_id,
                    CatalogRelation.active.is_(True),
                )
            )
            indexes = session.scalar(
                select(func.count()).select_from(CatalogIndex).where(
                    CatalogIndex.table_id.in_(table_ids),
                    CatalogIndex.active.is_(True),
                )
            )
            last = session.scalar(
                select(CatalogAnalysisRun)
                .where(
                    CatalogAnalysisRun.source_id == target_id,
                    CatalogAnalysisRun.status == "SUCCESS",
                )
                .order_by(CatalogAnalysisRun.id.desc())
                .limit(1)
            )
            return {
                "source_id": source.id,
                "source_name": source.source_name,
                "tables": int(tables or 0),
                "columns": int(columns or 0),
                "relations": int(relations or 0),
                "indexes": int(indexes or 0),
                "last_success_run_id": last.id if last else None,
                "last_success_fingerprint": last.schema_fingerprint if last else None,
                "last_success_at": last.finished_at if last else None,
            }
        finally:
            session.close()
