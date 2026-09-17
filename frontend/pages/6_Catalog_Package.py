"""Streamlit page for finalized DEMIS Catalog Package handoff."""

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
        timeout=kwargs.pop("timeout", 180),
        **kwargs,
    )


def _filename_from_disposition(value: str | None) -> str:
    if not value:
        return "demis_catalog_package_v2.zip"
    match = re.search(r'filename="([^"]+)"', value)
    return match.group(1) if match else "demis_catalog_package_v2.zip"


def target_label(target: dict[str, Any]) -> str:
    return (
        f"{target.get('source_name')} / {target.get('db_type')} / "
        f"{target.get('database_name')}"
    )


st.set_page_config(
    page_title="Catalog Package · DEMIS Schema Analyzer",
    page_icon="📦",
    layout="wide",
)

st.title("Catalog Package Finalization")
st.caption(
    "Catalog JSON, 최신 성공 분석 Run, 물리 Schema Snapshot, Preflight, Run Diff, "
    "DB 분석서 DOCX를 하나의 전달용 ZIP으로 묶습니다."
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
    st.info("등록된 Target이 없습니다. DB Targets에서 먼저 등록하세요.")
    st.stop()

labels = [target_label(target) for target in targets]
selected_label = st.selectbox("Target", labels, key="final_package_target")
target = targets[labels.index(selected_label)]
source_id = int(target["id"])

try:
    manifest_response = api_get(
        f"/api/v1/catalog/package/{source_id}/final/manifest",
        timeout=180,
    )
    manifest_response.raise_for_status()
    manifest = manifest_response.json()
except Exception as exc:  # noqa: BLE001
    st.error(f"최종 Package manifest 생성 실패: {exc}")
    st.stop()

readiness = manifest.get("package_readiness") or "UNKNOWN"
if readiness == "READY":
    st.success("READY — 전달용 Catalog Package 구성요소가 준비되었습니다.")
elif readiness == "WARNING":
    st.warning("WARNING — Package 생성은 가능하지만 확인이 필요한 구성요소가 있습니다.")
else:
    st.error("BLOCKED — 최신 분석/검증 상태를 확인하세요.")

issues = manifest.get("readiness_issues") or []
for issue in issues:
    st.caption(f"• {issue}")

counts = manifest.get("counts") or {}
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Tables", counts.get("tables", 0))
c2.metric("Columns", counts.get("columns", 0))
c3.metric("Relations", counts.get("relations", 0))
c4.metric("Indexes", counts.get("indexes", 0))
c5.metric("Categories", counts.get("categories", 0))

st.caption(
    f"Package v{manifest.get('package_version') or '-'} · "
    f"fingerprint={manifest.get('schema_fingerprint') or '-'}"
)

artifacts = manifest.get("artifacts") or {}
rows = []
for key, label in [
    ("analysis_run", "Latest Analysis Run"),
    ("schema_snapshot", "Schema Snapshot"),
    ("preflight", "DB Analysis Preflight"),
    ("latest_diff", "Latest Run Diff"),
    ("db_analysis_report", "DB Analysis Report"),
]:
    item = artifacts.get(key) or {}
    rows.append(
        {
            "Artifact": label,
            "Available": "YES" if item.get("available") else "NO",
            "Status": item.get("status") or (
                "IDENTICAL" if item.get("identical") is True else "-"
            ),
            "Run / Range": (
                f"#{item.get('run_id')}" if item.get("run_id") is not None else (
                    f"#{item.get('base_run_id')} → #{item.get('target_run_id')}"
                    if item.get("base_run_id") is not None
                    else "-"
                )
            ),
            "Path": item.get("path") or "-",
        }
    )

st.markdown("### Package 구성")
st.dataframe(rows, use_container_width=True, hide_index=True)

with st.expander("포함 파일", expanded=False):
    st.dataframe(manifest.get("files") or [], use_container_width=True, hide_index=True)

st.info(
    "v1의 root Catalog JSON 파일은 그대로 유지하며, v2에서는 analysis / validation / diff / reports "
    "아티팩트를 추가합니다. Host·Username·Password·암호화 Credential·Connection Option은 포함하지 않습니다."
)

state_key = f"final_catalog_package_{source_id}"
if st.button("최종 Catalog Package 생성", type="primary", use_container_width=True):
    try:
        with st.spinner("전달용 ZIP Package 생성 중..."):
            response = api_get(
                f"/api/v1/catalog/package/{source_id}/final/download",
                timeout=240,
            )
            response.raise_for_status()
        st.session_state[state_key] = {
            "content": response.content,
            "filename": _filename_from_disposition(response.headers.get("content-disposition")),
            "version": response.headers.get("x-catalog-package-version"),
            "readiness": response.headers.get("x-catalog-package-readiness"),
        }
    except Exception as exc:  # noqa: BLE001
        st.error(f"최종 Catalog Package 생성 실패: {exc}")

package = st.session_state.get(state_key)
if package:
    st.success(
        f"Package 생성 완료 · version={package.get('version') or '-'} · "
        f"readiness={package.get('readiness') or '-'} · {len(package['content']):,} bytes"
    )
    st.download_button(
        "ZIP 다운로드",
        data=package["content"],
        file_name=package["filename"],
        mime="application/zip",
        use_container_width=True,
        key=f"download_final_catalog_package_{source_id}",
    )
