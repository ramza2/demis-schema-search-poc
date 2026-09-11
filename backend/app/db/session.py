"""Database engine helpers for medical_demo and schema_catalog."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

_engines: dict[str, Engine] = {}
_session_factories: dict[str, sessionmaker[Session]] = {}


def _get_engine(name: str, url: str) -> Engine:
    if name not in _engines:
        _engines[name] = create_engine(url, pool_pre_ping=True, future=True)
    return _engines[name]


def get_medical_engine(settings: Settings | None = None) -> Engine:
    cfg = settings or get_settings()
    return _get_engine("medical", cfg.medical_db_url)


def get_catalog_engine(settings: Settings | None = None) -> Engine:
    cfg = settings or get_settings()
    return _get_engine("catalog", cfg.catalog_db_url)


def get_medical_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    if "medical" not in _session_factories:
        _session_factories["medical"] = sessionmaker(
            bind=get_medical_engine(settings), autoflush=False, autocommit=False, future=True
        )
    return _session_factories["medical"]


def get_catalog_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    if "catalog" not in _session_factories:
        _session_factories["catalog"] = sessionmaker(
            bind=get_catalog_engine(settings), autoflush=False, autocommit=False, future=True
        )
    return _session_factories["catalog"]


@contextmanager
def medical_session() -> Generator[Session, None, None]:
    session = get_medical_session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def catalog_session() -> Generator[Session, None, None]:
    session = get_catalog_session_factory()()
    try:
        yield session
    finally:
        session.close()


def check_connection(engine: Engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False
