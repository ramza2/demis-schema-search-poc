"""Unit checks for target dashboard helper behavior."""

from __future__ import annotations

from target_dashboard import default_analysis_schemas


def test_default_analysis_schemas_strips_whitespace() -> None:
    assert default_analysis_schemas({"default_schema": "  DEMIS_OWNER  "}) == ["DEMIS_OWNER"]


def test_default_analysis_schemas_handles_missing_schema() -> None:
    assert default_analysis_schemas({"default_schema": None}) == []
    assert default_analysis_schemas({}) == []
