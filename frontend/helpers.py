"""Frontend helpers (unit-testable; no Streamlit dependency)."""

from __future__ import annotations

import requests

# Backend TARGET_DB_CONNECT_TIMEOUT_SECONDS default is 5s; keep HTTP slightly longer.
TEST_CONNECTION_TIMEOUT_SECONDS = 12
DISCOVER_SCHEMAS_TIMEOUT_SECONDS = 15
LOAD_TARGETS_TIMEOUT_SECONDS = 8

HOST_INPUT_HINT = "프로토콜 없이 hostname 또는 IP만 입력"

TIMEOUT_USER_MESSAGE = (
    "Target DB 연결 시간이 초과되었습니다. Host/Port/방화벽을 확인하세요."
)


def format_connection_request_error(exc: BaseException) -> str:
    """User-facing message for Test Connection / Discover request failures."""
    if isinstance(exc, requests.Timeout):
        return TIMEOUT_USER_MESSAGE
    if isinstance(exc, requests.ConnectionError):
        return f"Target DB 연결에 실패했습니다: {exc}"
    return f"Target DB 연결에 실패했습니다: {exc}"


def tabs_created_before_targets_load(source: str) -> bool:
    """Structural check: st.tabs(...) must appear before load_targets() call site."""
    tabs_idx = source.find("st.tabs(")
    load_idx = source.find("targets, targets_load_error = load_targets(")
    if tabs_idx < 0 or load_idx < 0:
        return False
    return tabs_idx < load_idx
