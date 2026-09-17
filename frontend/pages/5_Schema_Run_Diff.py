"""Streamlit page for comparing persisted successful schema analysis runs."""

from __future__ import annotations

import json
import os
from typing import Any

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def api_get(path: str, **kwargs: Any) -> requests.Response:
    return requests.get(
        f"{BACKEND_URL}{path}",
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )


def api_post(path: str, **kwargs: Any) -> requests.Response:
    return requests.post(
        f"{BACKEND_URL}{path}",
        timeout=kwargs.pop("timeout", 60),
        **kwargs,
    )


def target_label(target: dict[str, Any]) -> str:
    return (
        f"{target.get('source_name')} / {target.get('db_type')} / "
        f"{target.get('database_name')}"
    )


def run_label(run: dict[str, Any]) -> str:
    fingerprint = str(run.get("schema_fingerprint") or "-")
    if fingerprint != "-":
        fingerprint = fingerprint[:12]
    snapshot = "snapshot" if run.get("snapshot_available") else "no snapshot"
    return (
        f"Run #{run.get('run_id')} · {run.get('target_schema') or '-'} · "
        f"{fingerprint} · {snapshot}"
    )


def count_text(item: dict[str, Any] | None) -> str:
    item = item or {}
    return (
        f"+{int(item.get('added') or 0)}  "
        f"-{int(item.get('removed') or 0)}  "
        f"~{int(item.get('changed') or 0)}"
    )


def compact_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


st.set_page_config(
    page_title="Schema Run Diff · DEMIS Schema Analyzer",
    page_icon="🔎",
    layout="wide",
)

st.title("Schema Run Diff")
st.caption(
    "SUCCESS 분석 Run별 물리 Schema Snapshot을 비교합니다. "
    "Table·Column·PK/UK·FK·Index의 Added / Removed / Changed를 확인할 수 있습니다."
)

try:
    health = api_get("/health", timeout=5)
    health.raise_for_status()
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.stop()

try:
    response = api_get("/api/v1/targets", timeout=10)
    response.raise_for_status()
    targets = response.json()
    if not isinstance(targets, list):
        targets = []
except Exception as exc:  # noqa: BLE001
    st.error(f"Target 목록 로드 실패: {exc}")
    st.stop()

if not targets:
    st.info("등록된 Target이 없습니다. 메인 화면의 DB Targets에서 먼저 등록하세요.")
    st.stop()

labels = [target_label(target) for target in targets]
selected_label = st.selectbox("Target", labels, key="schema_diff_target")
target = targets[labels.index(selected_label)]
target_id = int(target["id"])

try:
    runs_response = api_get(
        f"/api/v1/schema-diff/targets/{target_id}/runs",
        timeout=30,
    )
    runs_response.raise_for_status()
    run_payload = runs_response.json()
    runs = run_payload.get("runs") or []
except Exception as exc:  # noqa: BLE001
    st.error(f"분석 Run 목록 로드 실패: {exc}")
    st.stop()

if not runs:
    st.info("비교할 SUCCESS Schema 분석 Run이 없습니다. 먼저 Schema 분석을 실행하세요.")
    st.stop()

latest = runs[0]
available = [run for run in runs if run.get("snapshot_available")]

st.markdown("### Snapshot 준비 상태")
run_rows = [
    {
        "Run": run.get("run_id"),
        "Schema": run.get("target_schema"),
        "Finished": run.get("finished_at"),
        "Tables": run.get("table_count", 0),
        "Columns": run.get("column_count", 0),
        "FK": run.get("relation_count", 0),
        "Indexes": run.get("index_count", 0),
        "Snapshot": "READY" if run.get("snapshot_available") else "UNAVAILABLE",
        "Capture": run.get("capture_mode") or "-",
    }
    for run in runs
]
st.dataframe(run_rows, use_container_width=True, hide_index=True)

if not latest.get("snapshot_available"):
    st.warning(
        "기존 Run은 상세 Snapshot이 보존되지 않았습니다. 현재 Catalog와 일치하는 "
        "최신 SUCCESS Run만 기준 Snapshot으로 안전하게 저장할 수 있습니다."
    )
    if st.button("최신 SUCCESS Run 기준 Snapshot 저장", type="primary"):
        try:
            with st.spinner("현재 Catalog를 최신 SUCCESS Run 기준 Snapshot으로 저장하는 중..."):
                response = api_post(
                    f"/api/v1/schema-diff/targets/{target_id}/baseline",
                    timeout=60,
                )
                response.raise_for_status()
            body = response.json()
            st.success(
                f"Run #{body.get('run_id')} 기준 Snapshot 저장 완료 "
                f"({body.get('capture_mode')})"
            )
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(f"기준 Snapshot 저장 실패: {exc}")

if len(available) < 2:
    st.info(
        "Snapshot이 2개 이상 있어야 비교할 수 있습니다. 기준 Snapshot을 준비한 뒤 "
        "DB Targets에서 Schema 분석을 한 번 더 실행하면 새 SUCCESS Run Snapshot이 자동 저장됩니다."
    )
    st.stop()

st.divider()
st.markdown("### Run 비교")

available_labels = [run_label(run) for run in available]
run_by_label = {run_label(run): run for run in available}

left, right = st.columns(2)
base_default_index = 1 if len(available_labels) > 1 else 0
base_label = left.selectbox(
    "Base Run (이전)",
    available_labels,
    index=base_default_index,
    key=f"schema_diff_base_{target_id}",
)
target_label_selected = right.selectbox(
    "Target Run (이후)",
    available_labels,
    index=0,
    key=f"schema_diff_after_{target_id}",
)
base_run = run_by_label[base_label]
target_run = run_by_label[target_label_selected]

result_key = f"schema_diff_result_{target_id}"
if st.button("변경점 비교", type="primary", use_container_width=True):
    if int(base_run["run_id"]) == int(target_run["run_id"]):
        st.error("서로 다른 Run을 선택하세요.")
    else:
        try:
            with st.spinner("Schema Snapshot을 비교하는 중..."):
                response = api_get(
                    f"/api/v1/schema-diff/targets/{target_id}/compare",
                    params={
                        "base_run_id": int(base_run["run_id"]),
                        "target_run_id": int(target_run["run_id"]),
                    },
                    timeout=60,
                )
                response.raise_for_status()
                st.session_state[result_key] = response.json()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Run 비교 실패: {exc}")

result = st.session_state.get(result_key)
if result:
    summary = result.get("summary") or {}
    if result.get("identical"):
        st.success("두 Run의 물리 Schema Snapshot이 동일합니다.")
    else:
        st.warning(f"총 {summary.get('total_changes', 0)}건의 Schema 변경을 확인했습니다.")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tables", count_text(summary.get("tables")))
    c2.metric("Columns", count_text(summary.get("columns")))
    c3.metric("PK / UK", count_text(summary.get("key_constraints")))
    c4.metric("FK", count_text(summary.get("foreign_keys")))
    c5.metric("Indexes", count_text(summary.get("indexes")))

    changes = result.get("changes") or []
    if changes:
        rows = []
        for change in changes:
            before = change.get("before") or {}
            after = change.get("after") or {}
            changed_fields = change.get("changed_fields") or []
            detail_parts = []
            for field in changed_fields:
                detail_parts.append(
                    f"{field}: {compact_value(before.get(field))} → {compact_value(after.get(field))}"
                )
            rows.append(
                {
                    "Object Type": change.get("object_type"),
                    "Change": change.get("change_type"),
                    "Object": change.get("object_key"),
                    "Changed Fields": ", ".join(changed_fields) or "-",
                    "Detail": " | ".join(detail_parts) or "-",
                }
            )
        st.markdown("### 상세 변경점")
        st.dataframe(rows, use_container_width=True, hide_index=True)

        with st.expander("Raw Diff JSON", expanded=False):
            st.json(changes)
    else:
        st.caption("Added / Removed / Changed 항목이 없습니다.")

st.caption(
    "Run Diff는 저장된 물리 Schema 메타데이터만 비교합니다. 업무 의미나 변경 의도는 추론하지 않습니다."
)
