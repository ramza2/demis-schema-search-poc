"""Streamlit UI for Step 3 status + schema analyze + embedding pipeline."""

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
st.subheader("현재 Step: Step 3 - CPU-only Embedding Pipeline + pgvector")
st.write(
    "Raw Schema Catalog로부터 Search Document를 생성하고, "
    "CPU-only BGE-M3(또는 Fake) Embedding을 pgvector에 저장합니다. "
    "자연어 Semantic Search UI는 Step 4 범위입니다."
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
    st.caption(f"step={health.get('step', '')}")
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.info("docker compose up --build 후 Backend가 healthy 상태인지 확인하세요.")
    st.stop()

st.divider()
st.markdown("### 1) Schema Analyze")

if st.button("Schema Analyze 실행", type="primary"):
    with st.spinner("medical_demo 스키마 분석 중..."):
        try:
            analyze_resp = requests.post(f"{BACKEND_URL}/api/v1/schema/analyze", timeout=120)
            analyze_resp.raise_for_status()
            result = analyze_resp.json()
            if result.get("status") == "SUCCESS":
                st.success(
                    f"분석 성공 — tables={result.get('tables')}, columns={result.get('columns')}"
                )
            else:
                st.error(f"분석 실패: {result.get('error_message')}")
            st.json(result)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Analyze 호출 실패: {exc}")

st.divider()
st.markdown("### 2) Search Document Rebuild")

if st.button("Search Document Rebuild"):
    with st.spinner("Search Document 재생성 중..."):
        try:
            rebuild_resp = requests.post(
                f"{BACKEND_URL}/api/v1/embeddings/documents/rebuild", timeout=120
            )
            rebuild_resp.raise_for_status()
            rebuilt = rebuild_resp.json()
            st.success(
                f"documents={rebuilt.get('documents')} "
                f"(TABLE={rebuilt.get('tables')}, COLUMN={rebuilt.get('columns')}) / "
                f"created={rebuilt.get('created')}, updated={rebuilt.get('updated')}, "
                f"unchanged={rebuilt.get('unchanged')}"
            )
            st.json(rebuilt)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Rebuild 실패: {exc}")

st.divider()
st.markdown("### 3) Embedding Run (CPU)")

if st.button("Embedding Run"):
    with st.spinner("Embedding 실행 중 (CPU)..."):
        try:
            run_resp = requests.post(f"{BACKEND_URL}/api/v1/embeddings/run", timeout=3600)
            run_resp.raise_for_status()
            run = run_resp.json()
            st.success(
                f"run_id={run.get('run_id')} status={run.get('status')} "
                f"embedded={run.get('embedded')} skipped={run.get('skipped')} "
                f"failed={run.get('failed')}"
            )
            st.caption(f"model_key={run.get('model_key')}")
            st.json(run)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Embedding Run 실패: {exc}")

st.divider()
st.markdown("### Embedding Stats")

try:
    stats_resp = requests.get(f"{BACKEND_URL}/api/v1/embeddings/stats", timeout=10)
    stats_resp.raise_for_status()
    stats = stats_resp.json()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active Docs", stats.get("active_documents", 0))
    c2.metric("TABLE", stats.get("table_documents", 0))
    c3.metric("COLUMN", stats.get("column_documents", 0))
    c4.metric("Embeddings", stats.get("embedding_count", 0))
    st.caption(
        f"provider={stats.get('embedding_provider')} device={stats.get('embedding_device')} "
        f"dim={stats.get('embedding_dimension')} stale={stats.get('stale_documents')}"
    )
    if stats.get("model_keys"):
        st.write("model_keys:", stats.get("model_keys"))
except Exception as exc:  # noqa: BLE001
    st.warning(f"Stats 조회 실패: {exc}")

st.divider()
st.markdown("### 최근 Embedding Runs")
try:
    runs_resp = requests.get(f"{BACKEND_URL}/api/v1/embeddings/runs", params={"limit": 5}, timeout=10)
    runs_resp.raise_for_status()
    runs = runs_resp.json()
    if not runs:
        st.info("아직 Embedding Run 이력이 없습니다.")
    else:
        st.dataframe(runs, use_container_width=True)
except Exception as exc:  # noqa: BLE001
    st.warning(f"Run 목록 조회 실패: {exc}")

st.divider()
st.markdown("### 향후 구현 예정 (Step 4+)")
st.markdown(
    """
1. **Semantic Search** — Query Embedding + cosine similarity  
2. **Keyword / Hybrid Search** — synonym + RRF  
3. **FK Relation Expansion**  
4. **자연어 검색 UI**

이번 Step에서는 검색 Query 입력창을 제공하지 않습니다.
"""
)
