"""Ensure schema_catalog tables exist via ORM (works inside backend container)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_catalog_engine, get_catalog_session_factory
from app.models.catalog import CatalogBase, CatalogSource


def ensure_catalog_schema(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    engine = get_catalog_engine(cfg)
    CatalogBase.metadata.create_all(bind=engine)
    _migrate_relation_natural_key(engine)
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


def _migrate_relation_natural_key(engine: Engine) -> None:
    """
    Migrate catalog_relation unique key from (source_id, constraint_name)
    to (source_table_id, constraint_name) for existing volumes.
    """
    with engine.begin() as conn:
        # Drop legacy unique constraints/indexes if present.
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS catalog_relation
                    DROP CONSTRAINT IF EXISTS catalog_relation_source_id_constraint_name_key
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS catalog_relation
                    DROP CONSTRAINT IF EXISTS uq_catalog_relation
                """
            )
        )
        # Recreate the corrected unique constraint when missing.
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'uq_catalog_relation'
                          AND conrelid = 'catalog_relation'::regclass
                    ) THEN
                        ALTER TABLE catalog_relation
                            ADD CONSTRAINT uq_catalog_relation
                            UNIQUE (source_table_id, constraint_name);
                    END IF;
                END
                $$;
                """
            )
        )


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
