"""Streamlit UI for Step 1 status dashboard."""

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
st.subheader("현재 Step: Step 1 - Foundation / Mock Medical DB")
st.write(
    "복잡한 의료 DB 스키마를 자동 분석·임베딩하여 자연어로 Table/Column/Relationship을 "
    "검색할 수 있는지 검증하기 위한 PoC입니다."
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
    st.json(health)
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.info("docker compose up --build 후 Backend가 healthy 상태인지 확인하세요.")

st.divider()
st.markdown("### 향후 구현 예정")
st.markdown(
    """
1. **Step 2** — Schema Analyzer + Schema Catalog  
2. **Step 3** — CPU-only Embedding Pipeline + PostgreSQL/pgvector  
3. **Step 4** — Semantic / Keyword Hybrid Search + FK Relation Expansion  
4. **Step 5** — Streamlit Schema Explorer / Natural Language Search UI  
5. **Step 6** — 정확도 평가 및 기술검증  

이번 Step에서는 자연어 검색창, Embedding, Schema Explorer를 제공하지 않습니다.
"""
)
