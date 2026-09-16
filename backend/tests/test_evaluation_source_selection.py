"""Evaluation runner source-selection tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.evaluation.gold import GoldDataset
from app.evaluation.runner import (
    DEFAULT_SOURCE_NAME,
    OfficialEvaluationError,
    _assert_gold_valid_for_source,
    _resolve_evaluation_source,
    _schema_fingerprint,
    build_arg_parser,
)


def test_eval_cli_defaults_to_medical_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVALUATION_SOURCE_NAME", raising=False)
    args = build_arg_parser().parse_args([])
    assert args.source_name == DEFAULT_SOURCE_NAME == "medical_demo"


def test_eval_cli_accepts_oracle_source_name() -> None:
    args = build_arg_parser().parse_args(
        ["--source-name", "oracle_demis_mock", "--gold", "/tmp/oracle.json"]
    )
    assert args.source_name == "oracle_demis_mock"


def test_eval_cli_source_name_can_come_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALUATION_SOURCE_NAME", "oracle_demis_mock")
    args = build_arg_parser().parse_args([])
    assert args.source_name == "oracle_demis_mock"


def test_resolve_evaluation_source_returns_selected_catalog_source() -> None:
    class Session:
        def scalar(self, _stmt):
            return SimpleNamespace(id=92, source_name="oracle_demis_mock")

    source = _resolve_evaluation_source(Session(), "oracle_demis_mock")
    assert source.id == 92
    assert source.source_name == "oracle_demis_mock"


def test_resolve_evaluation_source_rejects_missing_source() -> None:
    class Session:
        def scalar(self, _stmt):
            return None

    with pytest.raises(OfficialEvaluationError, match="oracle_demis_mock"):
        _resolve_evaluation_source(Session(), "oracle_demis_mock")


def test_resolve_evaluation_source_rejects_empty_name() -> None:
    with pytest.raises(OfficialEvaluationError, match="must not be empty"):
        _resolve_evaluation_source(SimpleNamespace(), "   ")


def test_gold_validation_is_scoped_to_selected_source(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_validate(dataset, *, session, require_catalog, source_id):
        captured["dataset"] = dataset
        captured["session"] = session
        captured["require_catalog"] = require_catalog
        captured["source_id"] = source_id
        return []

    monkeypatch.setattr(
        "app.evaluation.runner.validate_gold_dataset",
        fake_validate,
    )
    dataset = GoldDataset(version="test", queries=[])
    session = object()
    _assert_gold_valid_for_source(dataset, session=session, source_id=92)

    assert captured == {
        "dataset": dataset,
        "session": session,
        "require_catalog": True,
        "source_id": 92,
    }


def test_gold_validation_error_mentions_selected_source_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.evaluation.runner.validate_gold_dataset",
        lambda *args, **kwargs: ["Q1: unknown gold table DEMIS_OWNER.TB_MISSING"],
    )
    dataset = GoldDataset(version="test", queries=[])

    with pytest.raises(OfficialEvaluationError, match="invalid for evaluation source"):
        _assert_gold_valid_for_source(dataset, session=object(), source_id=92)


def test_schema_fingerprint_filters_by_selected_source() -> None:
    class Result:
        def scalar(self):
            return "oracle-fingerprint"

    class Session:
        def __init__(self):
            self.params = None

        def execute(self, _stmt, params):
            self.params = params
            return Result()

    session = Session()
    value = _schema_fingerprint(session, source_id=92)

    assert value == "oracle-fingerprint"
    assert session.params == {"source_id": 92}
