"""Ensure schema_catalog tables exist via ORM (works inside backend container)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_catalog_engine, get_catalog_session_factory
from app.models.catalog import CatalogBase, CatalogSource


def ensure_catalog_schema(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    engine = get_catalog_engine(cfg)
    CatalogBase.metadata.create_all(bind=engine)
    factory = get_catalog_session_factory(cfg)
    session = factory()
    try:
        _ensure_default_source(session, cfg)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_default_source(session: Session, cfg: Settings) -> None:
    existing = session.scalar(
        select(CatalogSource).where(CatalogSource.source_name == "medical_demo")
    )
    if existing is None:
        session.add(
            CatalogSource(
                source_name="medical_demo",
                db_type="postgresql",
                host=cfg.medical_db_host,
                port=cfg.medical_db_port,
                database_name=cfg.medical_db_name,
                default_schema="public",
                enabled=True,
            )
        )
    else:
        # Refresh non-secret connection metadata only (never store password).
        existing.db_type = "postgresql"
        existing.host = cfg.medical_db_host
        existing.port = cfg.medical_db_port
        existing.database_name = cfg.medical_db_name
        existing.default_schema = "public"
        existing.enabled = True
