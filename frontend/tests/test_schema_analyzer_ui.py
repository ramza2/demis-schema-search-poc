"""Regression checks for the DEMIS Schema Analyzer UI shell."""

from __future__ import annotations

from pathlib import Path

from target_dashboard import default_analysis_schemas


FRONTEND_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (FRONTEND_ROOT / "app.py").read_text(encoding="utf-8")
TARGET_DASHBOARD_SOURCE = (FRONTEND_ROOT / "target_dashboard.py").read_text(encoding="utf-8")


def test_product_name_no_longer_uses_poc_label() -> None:
    assert 'page_title="DEMIS Schema Analyzer"' in APP_SOURCE
    assert 'st.title("DEMIS Schema Analyzer")' in APP_SOURCE
    assert "DEMIS Schema Semantic Search PoC" not in APP_SOURCE


def test_navigation_uses_analyzer_labels() -> None:
    assert '["DB Targets", "Catalog Explorer", "Schema Search", "검증 결과"]' in APP_SOURCE
    assert "render_target_dashboard(" in APP_SOURCE


def test_target_dashboard_exposes_primary_actions() -> None:
    for label in ["➕ Target 추가", "연결 테스트", "Schema 분석", "수정", "고급 작업", "삭제"]:
        assert label in TARGET_DASHBOARD_SOURCE


def test_default_analysis_schema_uses_target_default() -> None:
    assert default_analysis_schemas({"default_schema": "DEMIS_OWNER"}) == ["DEMIS_OWNER"]
    assert default_analysis_schemas({"default_schema": ""}) == []
    assert default_analysis_schemas({}) == []
