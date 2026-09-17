"""Build the finalized portable DEMIS Catalog Package v2."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.catalog import CatalogAnalysisRun, CatalogSource
from app.models.catalog_history import CatalogAnalysisSnapshot
from app.services.catalog_package import (
    PACKAGE_FORMAT,
    PACKAGE_ROOT,
    CatalogPackageResult,
    build_catalog_package,
)
from app.services.catalog_report import REPORT_VERSION, build_db_analysis_report
from app.services.catalog_validation_service import latest_preflight_result
from app.services.schema_diff_service import compare_snapshot_payloads


FINAL_PACKAGE_VERSION = "2.0"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _model_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value.dict()  # pragma: no cover - pydantic v1 compatibility


def _redact_text(value: str, secrets: list[str]) -> str:
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _sanitize_preflight(raw: dict[str, Any], source: CatalogSource) -> dict[str, Any]:
    """Keep readiness evidence while excluding connection identity/secrets."""
    secrets = [str(source.host or ""), str(source.username or "")]
    connection = raw.get("connection") or {}
    checks = []
    for item in raw.get("checks") or []:
        checks.append(
            {
                "key": item.get("key"),
                "name": item.get("name"),
                "status": item.get("status"),
                "schema_name": item.get("schema_name"),
                "count": item.get("count"),
                "detail": _redact_text(str(item.get("detail") or ""), secrets),
            }
        )
    return {
        "available": True,
        "target_id": raw.get("target_id"),
        "source_name": raw.get("source_name"),
        "db_type": raw.get("db_type"),
        "schemas": raw.get("schemas") or [],
        "status": raw.get("status"),
        "generated_at": raw.get("generated_at"),
        "connection": {
            "dbms_product": connection.get("dbms_product"),
            "db_version": connection.get("db_version"),
            "database_or_service": connection.get("database_or_service"),
            "current_user_exported": False,
        },
        "summary": raw.get("summary") or {},
        "checks": checks,
        "security": {
            "metadata_select_only": bool((raw.get("security") or {}).get("metadata_select_only")),
            "business_data_selected": bool((raw.get("security") or {}).get("business_data_selected")),
            "credentials_returned": False,
            "connection_host_exported": False,
            "username_exported": False,
        },
    }


def _latest_success(session: Session, source_id: int) -> CatalogAnalysisRun | None:
    return session.scalar(
        select(CatalogAnalysisRun)
        .where(
            CatalogAnalysisRun.source_id == source_id,
            CatalogAnalysisRun.status == "SUCCESS",
        )
        .order_by(CatalogAnalysisRun.id.desc())
        .limit(1)
    )


def _snapshot_for_run(session: Session, run_id: int | None) -> CatalogAnalysisSnapshot | None:
    if run_id is None:
        return None
    return session.scalar(
        select(CatalogAnalysisSnapshot).where(CatalogAnalysisSnapshot.run_id == run_id)
    )


def _latest_snapshot_rows(
    session: Session, source_id: int, limit: int = 2
) -> list[tuple[CatalogAnalysisSnapshot, CatalogAnalysisRun]]:
    return list(
        session.execute(
            select(CatalogAnalysisSnapshot, CatalogAnalysisRun)
            .join(CatalogAnalysisRun, CatalogAnalysisRun.id == CatalogAnalysisSnapshot.run_id)
            .where(
                CatalogAnalysisSnapshot.source_id == source_id,
                CatalogAnalysisRun.status == "SUCCESS",
            )
            .order_by(CatalogAnalysisRun.id.desc())
            .limit(limit)
        ).all()
    )


def _diff_payload(
    session: Session, source_id: int
) -> tuple[dict[str, Any], str]:
    rows = _latest_snapshot_rows(session, source_id, limit=2)
    if len(rows) < 2:
        payload = {
            "available": False,
            "reason": "At least two successful analysis snapshots are required.",
            "base_run_id": None,
            "target_run_id": int(rows[0][1].id) if rows else None,
            "identical": None,
            "summary": None,
            "changes": [],
        }
        md = (
            "# Latest Schema Run Diff\n\n"
            "Detailed diff is not available because fewer than two successful snapshots exist.\n"
        )
        return payload, md

    target_snapshot, target_run = rows[0]
    base_snapshot, base_run = rows[1]
    summary, changes = compare_snapshot_payloads(base_snapshot.payload, target_snapshot.payload)
    summary_dict = _model_dict(summary)
    change_dicts = [_model_dict(change) for change in changes]
    identical = summary.total_changes == 0
    payload = {
        "available": True,
        "base_run_id": int(base_run.id),
        "target_run_id": int(target_run.id),
        "base_schema_fingerprint": base_run.schema_fingerprint,
        "target_schema_fingerprint": target_run.schema_fingerprint,
        "identical": identical,
        "summary": summary_dict,
        "changes": change_dicts,
    }

    lines = [
        "# Latest Schema Run Diff",
        "",
        f"- Base Run: #{base_run.id}",
        f"- Target Run: #{target_run.id}",
        f"- Identical: {'YES' if identical else 'NO'}",
        f"- Total Changes: {summary.total_changes}",
        "",
        "| Object | Added | Removed | Changed |",
        "|---|---:|---:|---:|",
    ]
    for label, key in [
        ("Tables", "tables"),
        ("Columns", "columns"),
        ("PK / UK", "key_constraints"),
        ("FK", "foreign_keys"),
        ("Indexes", "indexes"),
    ]:
        item = summary_dict[key]
        lines.append(
            f"| {label} | {item['added']} | {item['removed']} | {item['changed']} |"
        )
    lines.append("")
    if change_dicts:
        lines.append("## Changes")
        lines.append("")
        for change in change_dicts:
            lines.append(
                f"- `{change['change_type']}` {change['object_type']} `{change['object_key']}`"
            )
    else:
        lines.append("No Added / Removed / Changed items were detected.")
    lines.append("")
    return payload, "\n".join(lines)


def _package_readiness(
    latest_success: CatalogAnalysisRun | None,
    latest_snapshot: CatalogAnalysisSnapshot | None,
    preflight_payload: dict[str, Any],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if latest_success is None:
        return "BLOCKED", ["No successful Schema analysis run exists."]
    if latest_snapshot is None:
        issues.append("Latest successful run has no persisted physical Schema Snapshot.")
    if not preflight_payload.get("available"):
        issues.append("No persisted DB Analysis Preflight result is available.")
    elif preflight_payload.get("status") == "BLOCKED":
        return "BLOCKED", ["Latest DB Analysis Preflight result is BLOCKED."]
    elif preflight_payload.get("status") != "READY":
        issues.append(
            f"Latest DB Analysis Preflight status is {preflight_payload.get('status') or 'UNKNOWN'}."
        )
    return ("WARNING", issues) if issues else ("READY", [])


def _readme() -> bytes:
    text = """# DEMIS Catalog Package v2\n\nThis package is the portable handoff artifact produced by DEMIS Schema Analyzer.\n\n## Core Catalog\n- database.json\n- tables.json\n- columns.json\n- relations.json\n- indexes.json\n- categories.json\n- erd.json\n\n## Finalization Artifacts\n- analysis/latest_run.json: latest successful Schema analysis provenance\n- analysis/schema_snapshot.json: append-only physical snapshot for the latest successful Run\n- validation/preflight.json: latest persisted metadata-only readiness check\n- diff/latest.json and diff/latest_summary.md: latest two available successful Snapshot comparison\n- reports/: human-readable DOCX DB analysis report\n\nConnection host, username, password, encrypted credential and connection options are intentionally excluded.\nBusiness meaning is not inferred from names when no verified metadata exists.\n"""
    return text.encode("utf-8")


def build_final_catalog_package(session: Session, source_id: int) -> CatalogPackageResult:
    """Build v2 package while preserving all v1 root Catalog JSON files."""
    source = session.get(CatalogSource, source_id)
    if source is None:
        raise LookupError("catalog source not found")

    legacy = build_catalog_package(session, source_id)
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(legacy.content)) as archive:
        prefix = f"{PACKAGE_ROOT}/"
        for name in archive.namelist():
            if not name.startswith(prefix):
                continue
            relative = name[len(prefix) :]
            if not relative or relative == "manifest.json":
                continue
            files[relative] = archive.read(name)

    latest_success = _latest_success(session, source_id)
    latest_snapshot = _snapshot_for_run(
        session, int(latest_success.id) if latest_success is not None else None
    )

    latest_run_payload = {
        "available": latest_success is not None,
        "run": None,
    }
    if latest_success is not None:
        latest_run_payload["run"] = {
            "run_id": int(latest_success.id),
            "status": latest_success.status,
            "target_schema": latest_success.target_schema,
            "started_at": _iso(latest_success.started_at),
            "finished_at": _iso(latest_success.finished_at),
            "schema_fingerprint": latest_success.schema_fingerprint,
            "counts": {
                "tables": latest_success.table_count or 0,
                "columns": latest_success.column_count or 0,
                "relations": latest_success.relation_count or 0,
                "indexes": latest_success.index_count or 0,
            },
        }
    files["analysis/latest_run.json"] = _json_bytes(latest_run_payload)

    snapshot_payload = {
        "available": latest_snapshot is not None,
        "run_id": int(latest_success.id) if latest_success is not None else None,
        "snapshot_version": latest_snapshot.snapshot_version if latest_snapshot else None,
        "capture_mode": latest_snapshot.capture_mode if latest_snapshot else None,
        "created_at": _iso(latest_snapshot.created_at) if latest_snapshot else None,
        "payload": latest_snapshot.payload if latest_snapshot else None,
    }
    files["analysis/schema_snapshot.json"] = _json_bytes(snapshot_payload)

    preflight_row = latest_preflight_result(session, source_id)
    if preflight_row is None:
        preflight_payload = {
            "available": False,
            "status": "NOT_AVAILABLE",
            "reason": "Run DB Analysis Preflight to include current readiness evidence.",
        }
    else:
        preflight_payload = _sanitize_preflight(preflight_row.result_json, source)
    files["validation/preflight.json"] = _json_bytes(preflight_payload)

    diff_payload, diff_summary = _diff_payload(session, source_id)
    files["diff/latest.json"] = _json_bytes(diff_payload)
    files["diff/latest_summary.md"] = diff_summary.encode("utf-8")

    report = build_db_analysis_report(session, source_id)
    report_path = f"reports/{report.filename}"
    files[report_path] = report.content
    files["PACKAGE_README.md"] = _readme()

    readiness, readiness_issues = _package_readiness(
        latest_success, latest_snapshot, preflight_payload
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "package_format": PACKAGE_FORMAT,
        "package_version": FINAL_PACKAGE_VERSION,
        "generated_at": generated_at,
        "package_readiness": readiness,
        "readiness_issues": readiness_issues,
        "source": {
            "source_name": source.source_name,
            "db_type": source.db_type,
            "database_name": source.database_name,
            "default_schema": source.default_schema,
        },
        "schema_fingerprint": latest_success.schema_fingerprint if latest_success else None,
        "counts": legacy.manifest.get("counts") or {},
        "artifacts": {
            "analysis_run": {
                "available": latest_success is not None,
                "path": "analysis/latest_run.json",
                "run_id": int(latest_success.id) if latest_success else None,
            },
            "schema_snapshot": {
                "available": latest_snapshot is not None,
                "path": "analysis/schema_snapshot.json",
                "run_id": int(latest_success.id) if latest_success else None,
            },
            "preflight": {
                "available": bool(preflight_payload.get("available")),
                "path": "validation/preflight.json",
                "status": preflight_payload.get("status"),
                "generated_at": preflight_payload.get("generated_at"),
            },
            "latest_diff": {
                "available": bool(diff_payload.get("available")),
                "path": "diff/latest.json",
                "summary_path": "diff/latest_summary.md",
                "base_run_id": diff_payload.get("base_run_id"),
                "target_run_id": diff_payload.get("target_run_id"),
                "identical": diff_payload.get("identical"),
            },
            "db_analysis_report": {
                "available": True,
                "path": report_path,
                "report_version": REPORT_VERSION,
            },
        },
        "compatibility": {
            "v1_root_catalog_files_preserved": True,
            "consumer_guidance": (
                "Consumers may continue reading the v1 root JSON files. v2 consumers should also "
                "inspect package_readiness and artifacts."
            ),
        },
        "provenance_policy": legacy.manifest.get("provenance_policy") or {},
        "security": {
            "connection_host_exported": False,
            "username_exported": False,
            "password_exported": False,
            "encrypted_credential_exported": False,
            "connection_options_exported": False,
        },
        "files": [
            {
                "path": path,
                "sha256": _sha256(content),
                "bytes": len(content),
            }
            for path, content in sorted(files.items())
        ],
    }
    manifest_bytes = _json_bytes(manifest)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{PACKAGE_ROOT}/manifest.json", manifest_bytes)
        for path, content in sorted(files.items()):
            archive.writestr(f"{PACKAGE_ROOT}/{path}", content)

    safe_source = "".join(
        ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in source.source_name
    )
    filename = f"demis_catalog_package_{safe_source}_v2.zip"
    return CatalogPackageResult(filename=filename, content=buffer.getvalue(), manifest=manifest)
