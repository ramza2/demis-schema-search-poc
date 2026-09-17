"""Streamlit multipage entry for Table Explorer."""

from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

from table_explorer import render_table_explorer


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


def api_get(path: str, **kwargs: Any) -> requests.Response:
    return requests.get(f"{BACKEND_URL}{path}", timeout=kwargs.pop("timeout", 30), **kwargs)


st.set_page_config(
    page_title="Table Explorer · DEMIS Schema Analyzer",
    page_icon="🗂️",
    layout="wide",
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

render_table_explorer(targets=targets, api_get=api_get)
