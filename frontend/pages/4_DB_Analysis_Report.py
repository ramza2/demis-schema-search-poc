"""Streamlit page for generating the DB analysis DOCX report."""

from __future__ import annotations

import os
import re
from typing import Any

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def api_get(path: str, **kwargs: Any) -> requests.Response:
    return requests.get(
        f"{BACKEND_URL}{path}",
        timeout=kwargs.pop("timeout", 120),
        **kwargs,
    )


def _filename_from_disposition(value: str | None) -> str:
    if not value:
        return "DEMIS_DB_analysis_report.docx"
    match = re.search(r"filename\*=UTF-8''([^;]+)", value)
    if match:
        from urllib.parse import unquote

        return unquote(match.group(1))
    match = re.search(r'filename="([^"]+)"', value)
    return match.group(1) if match else "DEMIS_DB_analysis_report.docx"


st.set_page_config(
    page_title="DB Analysis Report · DEMIS Schema Analyzer",
    page_icon="📄",
    layout="wide",
)

st.title("DB Analysis Report")
st.caption(
    "분석된 Catalog를 기반으로 Table·Column·PK/FK·Index·Category를 포함한 "
    "DB 분석서를 DOCX로 생성합니다."
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
    targets = []

if not targets:
    st.info("등록된 Target이 없습니다. DB Targets에서 먼저 등록하세요.")
    st.stop()

labels = [
    f"{target.get('source_name')} / {target.get('db_type')} / {target.get('database_name')}"
    for target in targets
]
selected_label = st.selectbox("Target", labels, key="report_target")
target = targets[labels.index(selected_label)]
source_id = int(target["id"])

try:
    manifest_response = api_get(
        f"/api/v1/catalog/package/{source_id}/manifest",
        timeout=30,
    )
    manifest_response.raise_for_status()
    manifest = manifest_response.json()
except Exception as exc:  # noqa: BLE001
    st.error(f"Catalog manifest 로드 실패: {exc}")
    st.stop()

counts = manifest.get("counts") or {}
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tables", counts.get("tables", 0))
c2.metric("Columns", counts.get("columns", 0))
c3.metric("Relations", counts.get("relations", 0))
c4.metric("Indexes", counts.get("indexes", 0))
c5.metric("Categories", counts.get("categories", 0))

st.caption(
    f"source={manifest.get('source', {}).get('source_name')} · "
    f"fingerprint={manifest.get('schema_fingerprint') or '-'}"
)

with st.expander("보고서 포함 내용", expanded=False):
    st.markdown(
        """
- DB 기본정보 및 최근 성공 Schema 분석정보
- Catalog 통계와 DB COMMENT 보유 현황
- Table 요약 및 Table별 Column 상세명세
- PK/Unique Constraint, FK 관계 및 Column Mapping
- Index 정보
- Category 및 Table Category 할당 출처(MANUAL/AUTO/IMPORT)
- 연결 Host·Username·Password·Connection Option 제외
"""
    )

st.info(
    "물리 DB에서 확인된 정보와 의미 메타데이터를 구분하여 작성합니다. "
    "DB COMMENT가 없는 항목의 업무 의미를 Table/Column명만으로 임의 생성하지 않습니다."
)

state_key = f"db_report_{source_id}"
if st.button("DB 분석서 생성", type="primary", key="generate_db_report"):
    with st.spinner("DOCX 분석서 생성 중..."):
        try:
            report_response = api_get(
                f"/api/v1/catalog/report/{source_id}/download",
                timeout=180,
            )
            report_response.raise_for_status()
            st.session_state[state_key] = {
                "content": report_response.content,
                "filename": _filename_from_disposition(
                    report_response.headers.get("content-disposition")
                ),
                "version": report_response.headers.get("x-catalog-report-version"),
            }
        except Exception as exc:  # noqa: BLE001
            st.error(f"DB 분석서 생성 실패: {exc}")

report = st.session_state.get(state_key)
if report:
    st.success(
        f"분석서 생성 완료 · version={report.get('version') or '-'} · "
        f"{len(report['content']):,} bytes"
    )
    st.download_button(
        "DOCX 다운로드",
        data=report["content"],
        file_name=report["filename"],
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        use_container_width=True,
        key=f"download_db_report_{source_id}",
    )
