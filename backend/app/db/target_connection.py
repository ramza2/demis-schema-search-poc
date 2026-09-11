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
) -> Engine:
    url = build_target_url(info, password)
    connect_args: dict[str, Any] = {}
    db_type = normalize_db_type(info.db_type)
    if db_type == "oracle":
        # Thin mode is default for python-oracledb; no Instant Client required.
        connect_args = {}
    return create_engine(
        url,
        pool_pre_ping=pool_pre_ping,
        pool_size=1,
        max_overflow=0,
        connect_args=connect_args,
    )


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
                    "CURRENT_USER() AS current_user"
                )
            ).mappings().one()
            product = "MariaDB" if db_type == "mariadb" or "mariadb" in str(row["version"]).lower() else "MySQL"
            return {
                "connected": True,
                "dbms_product": product,
                "db_version": str(row["version"]),
                "database_or_service": str(row["database_name"] or ""),
                "current_user": str(row["current_user"]),
            }
        # Oracle
        row = conn.execute(
            text(
                "SELECT banner AS version FROM v$version WHERE banner LIKE 'Oracle%' "
                "AND ROWNUM = 1"
            )
        ).mappings().first()
        user_row = conn.execute(text("SELECT USER AS current_user FROM dual")).mappings().one()
        svc = conn.execute(
            text("SELECT SYS_CONTEXT('USERENV','SERVICE_NAME') AS svc FROM dual")
        ).mappings().one()
        return {
            "connected": True,
            "dbms_product": "Oracle",
            "db_version": str((row or {}).get("version") or "Oracle"),
            "database_or_service": str(svc["svc"] or ""),
            "current_user": str(user_row["current_user"]),
        }
