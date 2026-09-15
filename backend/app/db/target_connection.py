"""Target DB connection factory (password never persisted)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

SUPPORTED_DB_TYPES = frozenset({"postgresql", "mysql", "mariadb", "oracle"})

DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "oracle": 1521,
}

HOST_VALIDATION_MESSAGE = (
    "Host에는 프로토콜(http://, https://)이나 URL path가 아닌 "
    "hostname 또는 IP 주소만 입력하세요."
)


@dataclass(frozen=True)
class TargetConnectionInfo:
    db_type: str
    host: str
    port: int
    database_name: str
    username: str
    connection_options: dict[str, Any] | None = None


def normalize_db_type(db_type: str) -> str:
    value = (db_type or "").strip().lower()
    aliases = {
        "postgres": "postgresql",
        "pg": "postgresql",
        "mariadb": "mariadb",
        "mysql": "mysql",
        "oracle": "oracle",
    }
    normalized = aliases.get(value, value)
    if normalized not in SUPPORTED_DB_TYPES:
        raise ValueError(f"unsupported db_type: {db_type}")
    return normalized


def validate_target_host(host: str) -> str:
    """Reject protocol/URL-like Host values; accept hostname or IP (incl. IPv6)."""
    value = (host or "").strip()
    if not value:
        raise ValueError(HOST_VALIDATION_MESSAGE)
    lowered = value.lower()
    if "://" in value or lowered.startswith("http://") or lowered.startswith("https://"):
        raise ValueError(HOST_VALIDATION_MESSAGE)
    # Reject path-like values (e.g. "host/db"). IPv6 literals use ":" / optional "[]" only.
    if "/" in value:
        raise ValueError(HOST_VALIDATION_MESSAGE)
    return value


def mask_secrets(message: str, *secrets: str | None) -> str:
    """Redact credentials from exception/log text."""
    out = message or ""
    for secret in secrets:
        if secret and secret in out:
            out = out.replace(secret, "***")
    if "://" in out and "@" in out:
        # URL with credentials — drop sensitive middle
        try:
            scheme, rest = out.split("://", 1)
            if "@" in rest:
                after_at = rest.split("@", 1)[1]
                out = f"{scheme}://***@{after_at}"
        except ValueError:
            out = "connection error (details redacted)"
    return out


def build_connect_args(db_type: str, connect_timeout_seconds: float | int) -> dict[str, Any]:
    """Driver-level connect timeout kwargs for SQLAlchemy create_engine(connect_args=...)."""
    db_type = normalize_db_type(db_type)
    timeout = max(1, int(round(float(connect_timeout_seconds))))
    if db_type == "postgresql":
        # psycopg / libpq: connect_timeout is seconds (int).
        return {"connect_timeout": timeout}
    if db_type in {"mysql", "mariadb"}:
        # PyMySQL: connect/read/write timeouts in seconds.
        return {
            "connect_timeout": timeout,
            "read_timeout": timeout,
            "write_timeout": timeout,
        }
    # Oracle python-oracledb Thin: tcp_connect_timeout (seconds, float) is supported.
    return {"tcp_connect_timeout": float(timeout)}


def build_target_url(info: TargetConnectionInfo, password: str) -> str:
    db_type = normalize_db_type(info.db_type)
    user = quote_plus(info.username or "")
    pwd = quote_plus(password or "")
    host = info.host
    port = int(info.port or DEFAULT_PORTS[db_type])
    opts = info.connection_options or {}

    if db_type == "postgresql":
        db = quote_plus(info.database_name)
        return f"postgresql+psycopg://{user}:{pwd}@{host}:{port}/{db}"

    if db_type in {"mysql", "mariadb"}:
        db = quote_plus(info.database_name)
        # Both MySQL and MariaDB use PyMySQL driver (stable SQLAlchemy support).
        return f"mysql+pymysql://{user}:{pwd}@{host}:{port}/{db}?charset=utf8mb4"

    # Oracle Thin mode via python-oracledb
    service = str(opts.get("service_name") or info.database_name or "").strip()
    if not service:
        raise ValueError("Oracle requires service_name (connection_options or database_name)")
    # Easy Connect: host:port/service_name
    return f"oracle+oracledb://{user}:{pwd}@{host}:{port}/?service_name={quote_plus(service)}"


def create_target_engine(
    info: TargetConnectionInfo,
    password: str,
    *,
    pool_pre_ping: bool = True,
    connect_timeout_seconds: float | int | None = None,
) -> Engine:
    url = build_target_url(info, password)
    db_type = normalize_db_type(info.db_type)
    if connect_timeout_seconds is None:
        from app.core.config import get_settings

        connect_timeout_seconds = get_settings().target_db_connect_timeout_seconds
    connect_args = build_connect_args(db_type, connect_timeout_seconds)
    return create_engine(
        url,
        pool_pre_ping=pool_pre_ping,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )


def is_connection_timeout_error(exc: BaseException) -> bool:
    """Heuristic: driver/SQLAlchemy timeout vs other connection failures."""
    name = type(exc).__name__.lower()
    text_value = str(exc).lower()
    markers = (
        "timeout",
        "timed out",
        "time out",
        "deadline exceeded",
        "connection timed out",
    )
    if any(m in name for m in markers):
        return True
    return any(m in text_value for m in markers)


def probe_connection(engine: Engine, db_type: str) -> dict[str, Any]:
    """Return non-sensitive connection probe details."""
    db_type = normalize_db_type(db_type)
    with engine.connect() as conn:
        if db_type == "postgresql":
            row = conn.execute(
                text(
                    "SELECT version() AS version, current_database() AS database_name, "
                    "current_user AS current_user"
                )
            ).mappings().one()
            return {
                "connected": True,
                "dbms_product": "PostgreSQL",
                "db_version": str(row["version"]),
                "database_or_service": str(row["database_name"]),
                "current_user": str(row["current_user"]),
            }
        if db_type in {"mysql", "mariadb"}:
            row = conn.execute(
                text(
                    "SELECT VERSION() AS version, DATABASE() AS database_name, "
                    "CURRENT_USER() AS authenticated_user"
                )
            ).mappings().one()
            product = "MariaDB" if db_type == "mariadb" or "mariadb" in str(row["version"]).lower() else "MySQL"
            return {
                "connected": True,
                "dbms_product": product,
                "db_version": str(row["version"]),
                "database_or_service": str(row["database_name"] or ""),
                "current_user": str(row["authenticated_user"]),
            }
        # Oracle: basic connectivity via dual/sys_context (no V$ privilege required).
        user_row = conn.execute(text("SELECT USER AS current_user FROM dual")).mappings().one()
        svc = conn.execute(
            text("SELECT SYS_CONTEXT('USERENV','SERVICE_NAME') AS svc FROM dual")
        ).mappings().one()
        db_version = "unavailable"
        try:
            row = conn.execute(
                text(
                    "SELECT banner AS version FROM v$version WHERE banner LIKE 'Oracle%' "
                    "AND ROWNUM = 1"
                )
            ).mappings().first()
            if row and row.get("version"):
                db_version = str(row["version"])
            else:
                db_version = "Oracle"
        except Exception:  # noqa: BLE001 — V$VERSION may be denied for low-privilege accounts
            db_version = "unavailable"
        return {
            "connected": True,
            "dbms_product": "Oracle",
            "db_version": db_version,
            "database_or_service": str(svc["svc"] or ""),
            "current_user": str(user_row["current_user"]),
        }
