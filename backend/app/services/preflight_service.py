"""DB analysis readiness checks that never read business row data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.analyzers.factory import create_schema_inspector
from app.db.target_connection import (
    DEFAULT_PORTS,
    TargetConnectionInfo,
    create_target_engine,
    mask_secrets,
    normalize_db_type,
    probe_connection,
)
from app.schemas.preflight_api import (
    PreflightCheck,
    PreflightConnection,
    PreflightResponse,
    PreflightSecurity,
    PreflightSummary,
)
from app.services.target_service import TargetService


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error(exc: BaseException, *secrets: str | None) -> str:
    message = mask_secrets(f"{type(exc).__name__}: {exc}", *secrets)
    return message[:1000]


def _connection_info(source: Any) -> TargetConnectionInfo:
    db_type = normalize_db_type(source.db_type)
    return TargetConnectionInfo(
        db_type=db_type,
        host=source.host or "localhost",
        port=int(source.port or DEFAULT_PORTS[db_type]),
        database_name=source.database_name,
        username=source.username or "",
        connection_options=source.connection_options,
    )


class PreflightService:
    """Check whether a Target can be analyzed before creating a Catalog Run.

    All target-side queries are connection probes or schema metadata queries already
    used by the SchemaInspector implementations. No application/business table rows
    are selected and no Catalog analysis run is created.
    """

    def __init__(self, target_service: TargetService | None = None) -> None:
        self.target_service = target_service or TargetService()

    @staticmethod
    def _metadata_call(engine, inspector, method_name: str, schema_name: str):
        method: Callable[..., Any] | None = getattr(inspector, method_name, None)
        if method is None:
            raise RuntimeError(f"metadata capability is not implemented: {method_name}")
        # Use an independent connection for every capability. On PostgreSQL a failed
        # SELECT aborts the current transaction; separate connections keep later
        # readiness checks meaningful.
        with engine.connect() as conn:
            return method(conn, schema_name)

    @staticmethod
    def _summary(checks: list[PreflightCheck], totals: dict[str, int]) -> PreflightSummary:
        return PreflightSummary(
            passed=sum(1 for item in checks if item.status == "PASS"),
            warnings=sum(1 for item in checks if item.status == "WARNING"),
            blocked=sum(1 for item in checks if item.status == "BLOCKED"),
            tables=totals["tables"],
            columns=totals["columns"],
            primary_keys=totals["primary_keys"],
            unique_constraints=totals["unique_constraints"],
            foreign_keys=totals["foreign_keys"],
            indexes=totals["indexes"],
            table_comments=totals["table_comments"],
            column_comments=totals["column_comments"],
        )

    @staticmethod
    def _overall_status(checks: list[PreflightCheck]) -> str:
        if any(item.status == "BLOCKED" for item in checks):
            return "BLOCKED"
        if any(item.status == "WARNING" for item in checks):
            return "WARNING"
        return "READY"

    def run(
        self,
        target_id: int,
        password: str | None = None,
        schemas: list[str] | None = None,
    ) -> PreflightResponse:
        source = self.target_service.get_target(target_id)
        if not source.enabled:
            raise ValueError(f"target is disabled: {source.source_name}")

        requested = [str(item).strip() for item in (schemas or []) if str(item).strip()]
        schema_names = list(dict.fromkeys(requested or [source.default_schema]))
        if not schema_names:
            raise ValueError("at least one schema is required")

        resolved = self.target_service.resolve_password(source, password)
        info = _connection_info(source)
        checks: list[PreflightCheck] = []
        totals = {
            "tables": 0,
            "columns": 0,
            "primary_keys": 0,
            "unique_constraints": 0,
            "foreign_keys": 0,
            "indexes": 0,
            "table_comments": 0,
            "column_comments": 0,
        }
        connection = PreflightConnection()
        engine = None

        try:
            try:
                engine = create_target_engine(
                    info,
                    resolved,
                    connect_timeout_seconds=self.target_service._connect_timeout_seconds(),
                )
                probe = probe_connection(engine, info.db_type)
                connection = PreflightConnection(
                    dbms_product=probe.get("dbms_product"),
                    db_version=probe.get("db_version"),
                    database_or_service=probe.get("database_or_service"),
                    current_user=probe.get("current_user"),
                )
                checks.append(
                    PreflightCheck(
                        key="CONNECTION",
                        name="DB Connection",
                        status="PASS",
                        detail="Target DB connection and basic probe succeeded.",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    PreflightCheck(
                        key="CONNECTION",
                        name="DB Connection",
                        status="BLOCKED",
                        detail=_safe_error(exc, resolved, source.username),
                    )
                )
                checks.append(
                    PreflightCheck(
                        key="SAFETY_MODE",
                        name="Metadata-only safety",
                        status="PASS",
                        detail="Preflight does not SELECT business rows or modify the Target DB.",
                    )
                )
                return PreflightResponse(
                    target_id=target_id,
                    source_name=source.source_name,
                    db_type=info.db_type,
                    schemas=schema_names,
                    status="BLOCKED",
                    generated_at=_utcnow(),
                    connection=connection,
                    summary=self._summary(checks, totals),
                    checks=checks,
                    security=PreflightSecurity(),
                )

            inspector = create_schema_inspector(info.db_type, engine, info.database_name)
            discovered_schemas: list[str] | None = None
            try:
                discovered_schemas = inspector.list_schemas()
                checks.append(
                    PreflightCheck(
                        key="SCHEMA_DISCOVERY",
                        name="Schema discovery",
                        status="PASS",
                        count=len(discovered_schemas),
                        detail=f"Discovered {len(discovered_schemas)} analyzable schema(s).",
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(
                    PreflightCheck(
                        key="SCHEMA_DISCOVERY",
                        name="Schema discovery",
                        status="WARNING",
                        detail=(
                            "Schema listing is unavailable; direct checks for the requested "
                            f"schema(s) will continue. {_safe_error(exc, resolved, source.username)}"
                        ),
                    )
                )

            for schema_name in schema_names:
                if discovered_schemas is None:
                    schema_status = "WARNING"
                    schema_detail = "Schema discovery unavailable; validating by direct metadata access."
                elif schema_name in discovered_schemas:
                    schema_status = "PASS"
                    schema_detail = "Requested schema is visible to the Target account."
                else:
                    schema_status = "WARNING"
                    schema_detail = (
                        "Requested schema was not returned by schema discovery; direct metadata "
                        "checks will determine whether analysis is still possible."
                    )
                checks.append(
                    PreflightCheck(
                        key="TARGET_SCHEMA",
                        name="Target Schema",
                        status=schema_status,
                        schema_name=schema_name,
                        detail=schema_detail,
                    )
                )

                tables = None
                try:
                    tables = self._metadata_call(engine, inspector, "_fetch_tables", schema_name)
                    table_count = len(tables)
                    totals["tables"] += table_count
                    totals["table_comments"] += sum(
                        1 for table in tables if getattr(table, "table_comment", None)
                    )
                    checks.append(
                        PreflightCheck(
                            key="TABLE_METADATA",
                            name="Table metadata",
                            status="PASS" if table_count else "WARNING",
                            schema_name=schema_name,
                            count=table_count,
                            detail=(
                                f"Readable table metadata: {table_count}."
                                if table_count
                                else "No analyzable tables were found in this schema."
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        PreflightCheck(
                            key="TABLE_METADATA",
                            name="Table metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail=_safe_error(exc, resolved, source.username),
                        )
                    )

                columns = None
                try:
                    columns = self._metadata_call(engine, inspector, "_fetch_columns", schema_name)
                    column_count = len(columns)
                    totals["columns"] += column_count
                    totals["column_comments"] += sum(
                        1 for column in columns if getattr(column, "column_comment", None)
                    )
                    if tables and not column_count:
                        column_status = "BLOCKED"
                        column_detail = "Tables are visible but no column metadata is readable."
                    elif column_count:
                        column_status = "PASS"
                        column_detail = f"Readable column metadata: {column_count}."
                    else:
                        column_status = "WARNING"
                        column_detail = "No column metadata was found because the schema has no tables."
                    checks.append(
                        PreflightCheck(
                            key="COLUMN_METADATA",
                            name="Column metadata",
                            status=column_status,
                            schema_name=schema_name,
                            count=column_count,
                            detail=column_detail,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        PreflightCheck(
                            key="COLUMN_METADATA",
                            name="Column metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail=_safe_error(exc, resolved, source.username),
                        )
                    )

                try:
                    primary_keys = self._metadata_call(
                        engine, inspector, "_fetch_primary_keys", schema_name
                    )
                    unique_constraints = self._metadata_call(
                        engine, inspector, "_fetch_unique_constraints", schema_name
                    )
                    totals["primary_keys"] += len(primary_keys)
                    totals["unique_constraints"] += len(unique_constraints)
                    checks.append(
                        PreflightCheck(
                            key="KEY_METADATA",
                            name="PK / Unique metadata",
                            status="PASS",
                            schema_name=schema_name,
                            count=len(primary_keys) + len(unique_constraints),
                            detail=(
                                f"PK columns: {len(primary_keys)}, "
                                f"Unique columns: {len(unique_constraints)}."
                            ),
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        PreflightCheck(
                            key="KEY_METADATA",
                            name="PK / Unique metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail=_safe_error(exc, resolved, source.username),
                        )
                    )

                try:
                    foreign_keys = self._metadata_call(
                        engine, inspector, "_fetch_foreign_keys", schema_name
                    )
                    totals["foreign_keys"] += len(foreign_keys)
                    checks.append(
                        PreflightCheck(
                            key="FK_METADATA",
                            name="FK metadata",
                            status="PASS",
                            schema_name=schema_name,
                            count=len(foreign_keys),
                            detail=f"Readable FK relationships: {len(foreign_keys)}.",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        PreflightCheck(
                            key="FK_METADATA",
                            name="FK metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail=_safe_error(exc, resolved, source.username),
                        )
                    )

                try:
                    indexes = self._metadata_call(engine, inspector, "_fetch_indexes", schema_name)
                    totals["indexes"] += len(indexes)
                    checks.append(
                        PreflightCheck(
                            key="INDEX_METADATA",
                            name="Index metadata",
                            status="PASS",
                            schema_name=schema_name,
                            count=len(indexes),
                            detail=f"Readable non-PK/UK indexes: {len(indexes)}.",
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    checks.append(
                        PreflightCheck(
                            key="INDEX_METADATA",
                            name="Index metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail=_safe_error(exc, resolved, source.username),
                        )
                    )

                if tables is not None and columns is not None:
                    table_comment_count = sum(
                        1 for table in tables if getattr(table, "table_comment", None)
                    )
                    column_comment_count = sum(
                        1 for column in columns if getattr(column, "column_comment", None)
                    )
                    checks.append(
                        PreflightCheck(
                            key="COMMENT_METADATA",
                            name="DB COMMENT metadata",
                            status="PASS",
                            schema_name=schema_name,
                            count=table_comment_count + column_comment_count,
                            detail=(
                                f"Table comments: {table_comment_count}/{len(tables)}, "
                                f"Column comments: {column_comment_count}/{len(columns)}."
                            ),
                        )
                    )
                else:
                    checks.append(
                        PreflightCheck(
                            key="COMMENT_METADATA",
                            name="DB COMMENT metadata",
                            status="BLOCKED",
                            schema_name=schema_name,
                            detail="Table/Column metadata access failed, so COMMENT access cannot be verified.",
                        )
                    )

            checks.append(
                PreflightCheck(
                    key="SAFETY_MODE",
                    name="Metadata-only safety",
                    status="PASS",
                    detail=(
                        "Only DB connection probes and system/catalog metadata SELECTs were executed; "
                        "business table rows were not read and the Target DB was not modified."
                    ),
                )
            )

            return PreflightResponse(
                target_id=target_id,
                source_name=source.source_name,
                db_type=info.db_type,
                schemas=schema_names,
                status=self._overall_status(checks),
                generated_at=_utcnow(),
                connection=connection,
                summary=self._summary(checks, totals),
                checks=checks,
                security=PreflightSecurity(),
            )
        finally:
            if engine is not None:
                engine.dispose()
