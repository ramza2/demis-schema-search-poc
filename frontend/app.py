"""Streamlit UI for Step 2 status + schema analysis trigger."""

from __future__ import annotations

import os

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="DEMIS Schema Semantic Search PoC",
    page_icon="🏥",
    layout="centered",
)

st.title("DEMIS Schema Semantic Search PoC")
st.subheader("현재 Step: Step 2 - Schema Analyzer / Schema Catalog")
st.write(
    "분석 대상 의료 DB의 Schema Metadata를 자동 수집하여 "
    "schema_catalog에 구조화 저장하는 단계입니다. "
    "Embedding / Semantic Search는 아직 포함되지 않습니다."
)

st.divider()
st.markdown("### 서비스 상태")

try:
    resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    resp.raise_for_status()
    health = resp.json()
    st.success(f"Backend 연결 성공 (`{BACKEND_URL}`)")
    col1, col2, col3 = st.columns(3)
    col1.metric("Backend", health.get("backend", "unknown"))
    col2.metric("medical_demo", health.get("medical_db", "unknown"))
    col3.metric("schema_catalog", health.get("catalog_db", "unknown"))
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.info("docker compose up --build 후 Backend가 healthy 상태인지 확인하세요.")
    st.stop()

st.divider()
st.markdown("### Schema Analyze")

if st.button("Schema Analyze 실행", type="primary"):
    with st.spinner("medical_demo 스키마 분석 중..."):
        try:
            analyze_resp = requests.post(f"{BACKEND_URL}/api/v1/schema/analyze", timeout=120)
            analyze_resp.raise_for_status()
            result = analyze_resp.json()
            if result.get("status") == "SUCCESS":
                st.success(
                    f"분석 성공 (run_id={result.get('run_id')}) — "
                    f"tables={result.get('tables')}, columns={result.get('columns')}, "
                    f"relations={result.get('relations')}, indexes={result.get('indexes')}"
                )
            else:
                st.error(f"분석 실패: {result.get('error_message')}")
            st.json(result)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Analyze 호출 실패: {exc}")

st.markdown("### 최근 Analysis Run")
try:
    runs_resp = requests.get(f"{BACKEND_URL}/api/v1/schema/runs", params={"limit": 5}, timeout=10)
    runs_resp.raise_for_status()
    runs = runs_resp.json()
    if not runs:
        st.info("아직 분석 이력이 없습니다. 위에서 Analyze를 실행하세요.")
    else:
        latest = runs[0]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Tables", latest.get("table_count", 0))
        m2.metric("Columns", latest.get("column_count", 0))
        m3.metric("Relations", latest.get("relation_count", 0))
        m4.metric("Indexes", latest.get("index_count", 0))
        st.caption(
            f"최신 run_id={latest.get('id')} / status={latest.get('status')} / "
            f"schema={latest.get('target_schema')}"
        )
        st.dataframe(runs, use_container_width=True)
except Exception as exc:  # noqa: BLE001
    st.warning(f"Run 목록 조회 실패: {exc}")

st.divider()
st.markdown("### 향후 구현 예정")
st.markdown(
    """
1. **Step 3** — CPU-only Embedding Pipeline + PostgreSQL/pgvector  
2. **Step 4** — Semantic / Keyword Hybrid Search + FK Relation Expansion  
3. **Step 5** — Streamlit Schema Explorer / Natural Language Search UI  
4. **Step 6** — 정확도 평가 및 기술검증  

이번 Step에서는 자연어 검색창과 Embedding을 제공하지 않습니다.
"""
)
