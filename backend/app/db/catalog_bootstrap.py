"""Ensure schema_catalog tables exist via ORM (works inside backend container)."""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_catalog_engine, get_catalog_session_factory
from app.models.catalog import CatalogBase, CatalogSource


def ensure_catalog_schema(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    engine = get_catalog_engine(cfg)
    _ensure_vector_extension(engine)
    CatalogBase.metadata.create_all(bind=engine)
    _migrate_catalog_column_length_type(engine)
    _migrate_relation_natural_key(engine)
    _migrate_catalog_source_target_fields(engine)
    _update_step_meta(engine)
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


def _ensure_vector_extension(engine: Engine) -> None:
    """Activate pgvector safely on fresh and existing volumes."""
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def _migrate_catalog_column_length_type(engine: Engine) -> None:
    """Widen character_maximum_length for MySQL LONGTEXT/LONGBLOB metadata."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_schema = current_schema()
                          AND table_name = 'catalog_column'
                          AND column_name = 'character_maximum_length'
                          AND data_type = 'integer'
                    ) THEN
                        ALTER TABLE catalog_column
                            ALTER COLUMN character_maximum_length
                            TYPE BIGINT
                            USING character_maximum_length::BIGINT;
                    END IF;
                END
                $$;
                """
            )
        )


def _migrate_catalog_source_target_fields(engine: Engine) -> None:
    """Add Target Profile columns on existing catalog volumes."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS catalog_source
                    ADD COLUMN IF NOT EXISTS username VARCHAR(255)
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS catalog_source
                    ADD COLUMN IF NOT EXISTS connection_options JSONB
                """
            )
        )
        conn.execute(
            text(
                """
                ALTER TABLE IF EXISTS catalog_source
                    ADD COLUMN IF NOT EXISTS encrypted_password TEXT
                """
            )
        )
        conn.execute(
            text(
                """
                COMMENT ON COLUMN catalog_source.encrypted_password IS
                  'Fernet ciphertext for Target DB password; plaintext is never stored'
                """
            )
        )


def _update_step_meta(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO catalog_meta (meta_key, meta_value)
                VALUES
                    ('current_step', 'Multi-DB Target Analyzer + Schema Explorer'),
                    ('schema_version', '0.6.1')
                ON CONFLICT (meta_key) DO UPDATE
                SET meta_value = EXCLUDED.meta_value,
                    updated_at = CURRENT_TIMESTAMP
                """
            )
        )


def _migrate_relation_natural_key(engine: Engine) -> None:
    """
    Migrate catalog_relation unique key from (source_id, constraint_name)
    to (source_table_id, constraint_name) for existing volumes.
    """
    with engine.begin() as conn:
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
                username=cfg.medical_db_user,
                connection_options=None,
                enabled=True,
            )
        )
    else:
        existing.db_type = "postgresql"
        existing.host = cfg.medical_db_host
        existing.port = cfg.medical_db_port
        existing.database_name = cfg.medical_db_name
        existing.default_schema = "public"
        if not existing.username:
            existing.username = cfg.medical_db_user
        existing.enabled = True
