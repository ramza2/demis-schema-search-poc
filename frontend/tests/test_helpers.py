"""Frontend helper / structure tests."""

from __future__ import annotations

from pathlib import Path

import requests

from helpers import (
    HOST_INPUT_HINT,
    LOAD_TARGETS_TIMEOUT_SECONDS,
    TEST_CONNECTION_TIMEOUT_SECONDS,
    TIMEOUT_USER_MESSAGE,
    format_connection_request_error,
    tabs_created_before_targets_load,
)

FRONTEND_DIR = Path(__file__).resolve().parents[1]


def test_timeouts_are_bounded_and_ordered():
    assert 5 <= LOAD_TARGETS_TIMEOUT_SECONDS <= 10
    assert 10 <= TEST_CONNECTION_TIMEOUT_SECONDS <= 15
    assert TEST_CONNECTION_TIMEOUT_SECONDS > 5


def test_format_timeout_vs_connection_error():
    assert format_connection_request_error(requests.Timeout()) == TIMEOUT_USER_MESSAGE
    msg = format_connection_request_error(requests.ConnectionError("refused"))
    assert msg.startswith("Target DB 연결에 실패했습니다:")
    assert "refused" in msg


def test_host_hint_present():
    assert "hostname" in HOST_INPUT_HINT.lower() or "IP" in HOST_INPUT_HINT


def test_app_tabs_before_load_targets():
    source = (FRONTEND_DIR / "app.py").read_text(encoding="utf-8")
    assert tabs_created_before_targets_load(source)
    assert "HOST_INPUT_HINT" in source
    assert "TEST_CONNECTION_TIMEOUT_SECONDS" in source
    assert "format_connection_request_error" in source
    assert "Targets" in source and "Evaluation Results" in source and "st.tabs(" in source
