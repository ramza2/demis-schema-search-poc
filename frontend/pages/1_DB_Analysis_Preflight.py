"""Streamlit page for DB analysis preflight checks."""

from __future__ import annotations

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
        timeout=kwargs.pop("timeout", 180),
        **kwargs,
    )


def target_label(target: dict[str, Any]) -> str:
    return (
        f"{target.get('source_name')} / {target.get('db_type')} / "
        f"{target.get('database_name')}"
    )


def credential_payload(target: dict[str, Any]) -> dict[str, str] | None:
    if target.get("has_saved_password"):
        return {}
    if st.session_state.get("preflight_passwordless", False):
        return {"password": ""}
    password = st.session_state.get("preflight_password", "")
    if password:
        return {"password": str(password)}
    return None


st.set_page_config(
    page_title="DB Analysis Preflight · DEMIS Schema Analyzer",
    page_icon="🩺",
    layout="wide",
)

st.title("DB Analysis Preflight")
st.caption(
    "실제 Schema 분석 전에 DB 연결과 Catalog 메타데이터 접근 가능 여부를 점검합니다. "
    "업무 데이터 행은 조회하지 않으며 Target DB를 변경하지 않습니다."
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
selected_label = st.selectbox("Target", labels, key="preflight_target_label")
target = targets[labels.index(selected_label)]
target_id = int(target["id"])
has_saved = bool(target.get("has_saved_password"))

c1, c2, c3, c4 = st.columns(4)
c1.metric("DBMS", str(target.get("db_type") or "-").upper())
c2.metric("Database / Service", target.get("database_name") or "-")
c3.metric("Default Schema", target.get("default_schema") or "-")
c4.metric("Credential", "저장됨" if has_saved else "임시 입력 필요")

if not has_saved:
    st.warning("저장된 Credential이 없습니다. 아래 Credential은 이번 요청에만 사용됩니다.")
    passwordless = st.checkbox(
        "빈 비밀번호 사용",
        value=False,
        key="preflight_passwordless",
    )
    st.text_input(
        "임시 Password",
        type="password",
        key="preflight_password",
        disabled=passwordless,
    )

schema_state_key = f"preflight_discovered_schemas_{target_id}"
left, right = st.columns([1, 4])
if left.button("Schema 목록 조회", use_container_width=True):
    body = credential_payload(target)
    if body is None:
        st.error("Credential을 입력하세요.")
    else:
        try:
            response = api_post(
                f"/api/v1/targets/{target_id}/schemas",
                json=body,
                timeout=60,
            )
            response.raise_for_status()
            st.session_state[schema_state_key] = response.json().get("schemas") or []
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Schema 목록 조회 실패: {exc}")

schemas = st.session_state.get(schema_state_key, [])
default_schema = str(target.get("default_schema") or "").strip()
options = schemas or ([default_schema] if default_schema else [])
defaults = [default_schema] if default_schema and default_schema in options else options[:1]
selected_schemas = right.multiselect(
    "점검할 Schema",
    options=options,
    default=defaults,
    key=f"preflight_schemas_{target_id}",
)

st.info(
    "Preflight는 연결 Probe와 DB 시스템 Catalog/Metadata SELECT만 수행합니다. "
    "Table의 실제 업무 데이터 SELECT, DDL, DML은 수행하지 않습니다."
)

result_key = f"preflight_result_{target_id}"
if st.button("사전 점검 실행", type="primary", use_container_width=True):
    body = credential_payload(target)
    if body is None:
        st.error("Credential을 입력하세요.")
    elif not selected_schemas:
        st.error("점검할 Schema를 하나 이상 선택하세요.")
    else:
        payload: dict[str, Any] = {"schemas": selected_schemas}
        if "password" in body:
            payload["password"] = body["password"]
        try:
            with st.spinner("DB 분석 준비 상태를 점검하는 중..."):
                response = api_post(
                    f"/api/v1/preflight/targets/{target_id}",
                    json=payload,
                    timeout=180,
                )
                response.raise_for_status()
                st.session_state[result_key] = response.json()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Preflight 실행 실패: {exc}")

result = st.session_state.get(result_key)
if result:
    status = result.get("status") or "UNKNOWN"
    if status == "READY":
        st.success("READY — 현재 계정과 Schema로 분석을 시작할 수 있습니다.")
    elif status == "WARNING":
        st.warning("WARNING — 분석은 가능할 수 있으나 확인할 항목이 있습니다.")
    else:
        st.error("BLOCKED — 현재 상태로는 정상 Schema 분석을 보장할 수 없습니다.")

    connection = result.get("connection") or {}
    st.markdown("### 연결 정보")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Product", connection.get("dbms_product") or "-")
    d2.metric("Version", connection.get("db_version") or "-")
    d3.metric("DB / Service", connection.get("database_or_service") or "-")
    d4.metric("Current User", connection.get("current_user") or "-")

    summary = result.get("summary") or {}
    st.markdown("### 점검 요약")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("PASS", summary.get("passed", 0))
    s2.metric("WARNING", summary.get("warnings", 0))
    s3.metric("BLOCKED", summary.get("blocked", 0))
    s4.metric("Tables", summary.get("tables", 0))
    s5.metric("Columns", summary.get("columns", 0))

    checks = result.get("checks") or []
    rows = [
        {
            "Status": item.get("status"),
            "Check": item.get("name"),
            "Schema": item.get("schema_name") or "-",
            "Count": item.get("count") if item.get("count") is not None else "-",
            "Detail": item.get("detail"),
        }
        for item in checks
    ]
    st.markdown("### 상세 점검 결과")
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Metadata 수집 가능 수량", expanded=False):
        st.json(
            {
                "primary_keys": summary.get("primary_keys", 0),
                "unique_constraints": summary.get("unique_constraints", 0),
                "foreign_keys": summary.get("foreign_keys", 0),
                "indexes": summary.get("indexes", 0),
                "table_comments": summary.get("table_comments", 0),
                "column_comments": summary.get("column_comments", 0),
            }
        )

    security = result.get("security") or {}
    if (
        security.get("metadata_select_only") is True
        and security.get("business_data_selected") is False
        and security.get("credentials_returned") is False
    ):
        st.caption(
            "안전성: metadata SELECT only · business row 미조회 · Credential 응답 미포함"
        )
