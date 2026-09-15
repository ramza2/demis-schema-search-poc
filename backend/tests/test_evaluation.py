"""Step 5 evaluation unit tests (metrics + validation; fake allowed)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["EMBEDDING_PROVIDER"] = "fake"
os.environ["ALLOW_FAKE_SEMANTIC_SEARCH"] = "true"

from app.evaluation.experiments import EXPERIMENTS
from app.evaluation.gold import (
    GoldDataset,
    GoldQuery,
    GoldTargets,
    GoldValidationError,
    assert_valid_gold,
    load_gold_dataset,
    validate_gold_dataset,
)
from app.evaluation.metrics import (
    extract_table_candidates,
    first_relevant_rank,
    hit_at_k,
    mean,
    median,
    percentile,
    reciprocal_rank,
    relation_recall,
    set_recall_at_k,
    top1_primary_accuracy,
)
from app.evaluation.report import QueryEvalRow, summarize_rows, write_outputs
from app.evaluation.runner import OfficialEvaluationError, assert_official_provider, evaluate_query_result


GOLD_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "gold_schema_queries.json"
# In docker: /app/evaluation/...
if not GOLD_PATH.exists():
    GOLD_PATH = Path("/app/evaluation/gold_schema_queries.json")


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


def test_gold_dataset_loads_and_has_enough_queries() -> None:
    assert GOLD_PATH.exists(), f"missing gold file: {GOLD_PATH}"
    ds = load_gold_dataset(GOLD_PATH)
    assert len(ds.queries) >= 40
    assert len({q.id for q in ds.queries}) == len(ds.queries)


def test_duplicate_query_id_detected() -> None:
    ds = GoldDataset(
        version="t",
        queries=[
            GoldQuery("Q1", "ambiguous", "a", GoldTargets(primary_tables=["public.tb_pt_mst"])),
            GoldQuery("Q1", "ambiguous", "b", GoldTargets(primary_tables=["public.tb_pt_mst"])),
        ],
    )
    errs = validate_gold_dataset(ds, require_catalog=False)
    assert any("duplicate" in e for e in errs)


def test_unknown_gold_table_detected() -> None:
    from app.db.session import get_catalog_session_factory

    ds = GoldDataset(
        version="t",
        queries=[
            GoldQuery(
                "QX",
                "ambiguous",
                "x",
                GoldTargets(primary_tables=["public.tb_does_not_exist"]),
            )
        ],
    )
    session = get_catalog_session_factory()()
    try:
        errs = validate_gold_dataset(ds, session=session, require_catalog=True)
        assert any("unknown gold table" in e for e in errs)
    finally:
        session.close()


def test_table_candidate_dedup_uses_first_rank() -> None:
    rows = [
        _row(schema_name="public", table_name="tb_lab_rst", object_type="COLUMN", column_name="rst_val"),
        _row(schema_name="public", table_name="tb_lab_rst", object_type="TABLE", column_name=None),
        _row(schema_name="public", table_name="tb_lab_mst", object_type="TABLE", column_name=None),
    ]
    cands = extract_table_candidates(rows)
    assert [c.identity for c in cands] == ["public.tb_lab_rst", "public.tb_lab_mst"]
    assert cands[0].rank == 1


def test_top1_primary_and_hit_metrics() -> None:
    rows = [
        _row(schema_name="public", table_name="tb_lab_mst", object_type="TABLE", column_name=None),
        _row(schema_name="public", table_name="tb_lab_rst", object_type="TABLE", column_name=None),
    ]
    cands = extract_table_candidates(rows)
    primary = ["public.tb_lab_rst"]
    relevant = ["public.tb_lab_rst", "public.tb_lab_mst"]
    assert top1_primary_accuracy(cands, primary) is False
    assert hit_at_k(cands, relevant, 3) is True
    assert hit_at_k(cands, primary, 1) is False
    assert hit_at_k(cands, primary, 2) is True
    assert set_recall_at_k(cands, relevant, 2) == 1.0
    assert first_relevant_rank(cands, primary) == 2
    assert reciprocal_rank(2) == 0.5


def test_mean_recall_and_mrr_helpers() -> None:
    assert reciprocal_rank(1) == 1.0
    assert reciprocal_rank(None) == 0.0
    assert relation_recall(["public.tb_lab_rst"], ["public.tb_lab_rst", "public.tb_lab_ord"]) == 0.5


def test_latency_stats() -> None:
    vals = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert mean(vals) == 40.0
    assert median(vals) == 30.0
    assert percentile(vals, 95) == 100.0


def test_official_eval_blocks_fake_provider() -> None:
    from app.core.config import Settings

    with pytest.raises(OfficialEvaluationError):
        assert_official_provider(Settings(embedding_provider="fake"))


def test_evaluate_query_does_not_reorder_results() -> None:
    from app.evaluation.experiments import Experiment

    gold = GoldQuery(
        "Q",
        "clinical_natural_language",
        "q",
        GoldTargets(
            primary_tables=["public.tb_lab_rst"],
            acceptable_tables=["public.tb_lab_mst"],
        ),
    )
    direct = [
        _row(
            schema_name="public",
            table_name="tb_lab_mst",
            object_type="TABLE",
            column_name=None,
            document_id=1,
        ),
        _row(
            schema_name="public",
            table_name="tb_lab_rst",
            object_type="TABLE",
            column_name=None,
            document_id=2,
        ),
    ]
    # Capture order identity
    order_before = [d.table_name for d in direct]
    result = SimpleNamespace(
        direct_results=direct,
        related_tables=[],
        matched_concepts=[],
        expanded_terms=[],
        elapsed_ms=12.0,
        timings={"total_ms": 12.0},
    )
    exp = Experiment("hybrid_expansion", "hybrid", True, False)
    row = evaluate_query_result(gold_query=gold, experiment=exp, search_result=result)
    assert [d.table_name for d in direct] == order_before
    assert row.top1_table == "public.tb_lab_mst"
    assert row.primary_hit_top1 is False
    assert row.relevant_hit_top3 is True


def test_column_and_relation_metrics_in_evaluate() -> None:
    from app.evaluation.experiments import Experiment

    gold = GoldQuery(
        "Q",
        "relation",
        "q",
        GoldTargets(
            primary_tables=["public.tb_lab_rst"],
            relevant_columns=["public.tb_lab_rst.rst_val"],
            relation_tables=["public.tb_lab_rst", "public.tb_lab_ord"],
        ),
    )
    direct = [
        _row(
            schema_name="public",
            table_name="tb_lab_rst",
            object_type="COLUMN",
            column_name="rst_val",
        )
    ]
    related = [
        SimpleNamespace(schema_name="public", table_name="tb_lab_ord"),
    ]
    result = SimpleNamespace(
        direct_results=direct,
        related_tables=related,
        matched_concepts=[],
        expanded_terms=[],
        elapsed_ms=1.0,
        timings={},
    )
    exp = Experiment("hybrid_expansion_relation", "hybrid", True, True, 2, True)
    row = evaluate_query_result(gold_query=gold, experiment=exp, search_result=result)
    assert row.column_hit_top3 is True
    assert row.relation_recall == 1.0


def test_category_aggregation_and_csv_output(tmp_path: Path) -> None:
    rows = [
        QueryEvalRow(
            query_id="Q1",
            category="ambiguous",
            query="x",
            experiment="keyword_no_expansion",
            matched_concepts=[],
            expanded_terms=[],
            top1_table="public.tb_pt_mst",
            top3_tables=["public.tb_pt_mst"],
            top5_tables=["public.tb_pt_mst"],
            primary_hit_top1=True,
            relevant_hit_top3=True,
            relevant_hit_top5=True,
            primary_hit_top3=True,
            primary_hit_top5=True,
            set_recall_at_3=1.0,
            set_recall_at_5=1.0,
            primary_set_recall_at_3=1.0,
            primary_set_recall_at_5=1.0,
            first_relevant_rank=1,
            reciprocal_rank=1.0,
            primary_first_rank=1,
            primary_reciprocal_rank=1.0,
            column_hit_top3=None,
            column_hit_top5=None,
            column_set_recall_at_3=None,
            column_set_recall_at_5=None,
            column_mrr=None,
            relation_hit=None,
            relation_recall=None,
            total_ms=10.0,
            query_embedding_ms=None,
            semantic_search_ms=None,
            keyword_search_ms=5.0,
            relation_expansion_ms=None,
            gold_primary=["public.tb_pt_mst"],
            gold_acceptable=[],
            gold_columns=[],
            gold_relation_tables=[],
        )
    ]
    summary = summarize_rows(rows, experiment="keyword_no_expansion")
    assert summary["top1_primary_accuracy"] == 1.0
    write_outputs(
        tmp_path,
        rows=rows,
        experiment_summaries=[summary],
        category_rows=[{"experiment": "keyword_no_expansion", "category": "ambiguous", "query_count": 1}],
        metadata={"ok": True},
        deltas={},
        summary_lines=["ok"],
    )
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "query_results.csv").exists()
    assert (tmp_path / "query_results.jsonl").exists()
    assert (tmp_path / "failures.csv").exists()
    assert (tmp_path / "run_metadata.json").exists()


def test_experiments_include_required_modes() -> None:
    names = {e.name for e in EXPERIMENTS}
    assert {
        "keyword_no_expansion",
        "semantic_no_expansion",
        "semantic_expansion",
        "hybrid_no_expansion",
        "hybrid_expansion",
        "hybrid_expansion_relation",
    } <= names


def test_gold_file_validates_against_catalog() -> None:
    from app.db.session import get_catalog_session_factory

    ds = load_gold_dataset(GOLD_PATH)
    session = get_catalog_session_factory()()
    try:
        assert_valid_gold(ds, session=session)
    finally:
        session.close()
