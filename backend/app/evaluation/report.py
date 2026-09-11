"""Aggregate experiment and category metrics; write evaluation artifacts."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.evaluation.metrics import mean, median, percentile


@dataclass
class QueryEvalRow:
    query_id: str
    category: str
    query: str
    experiment: str
    matched_concepts: list[str]
    expanded_terms: list[str]
    top1_table: str | None
    top3_tables: list[str]
    top5_tables: list[str]
    primary_hit_top1: bool
    relevant_hit_top3: bool
    relevant_hit_top5: bool
    primary_hit_top3: bool
    primary_hit_top5: bool
    set_recall_at_3: float
    set_recall_at_5: float
    primary_set_recall_at_3: float
    primary_set_recall_at_5: float
    first_relevant_rank: int | None
    reciprocal_rank: float
    primary_first_rank: int | None
    primary_reciprocal_rank: float
    column_hit_top3: bool | None
    column_hit_top5: bool | None
    column_set_recall_at_3: float | None
    column_set_recall_at_5: float | None
    column_mrr: float | None
    relation_hit: bool | None
    relation_recall: float | None
    total_ms: float
    query_embedding_ms: float | None
    semantic_search_ms: float | None
    keyword_search_ms: float | None
    relation_expansion_ms: float | None
    gold_primary: list[str]
    gold_acceptable: list[str]
    gold_columns: list[str]
    gold_relation_tables: list[str]


def _bool_rate(rows: list[QueryEvalRow], attr: str) -> float:
    vals = [1.0 if getattr(r, attr) else 0.0 for r in rows if getattr(r, attr) is not None]
    return mean(vals)


def _float_mean(rows: list[QueryEvalRow], attr: str) -> float:
    vals = [float(getattr(r, attr)) for r in rows if getattr(r, attr) is not None]
    return mean(vals)


def summarize_rows(rows: list[QueryEvalRow], *, experiment: str | None = None) -> dict[str, Any]:
    subset = [r for r in rows if experiment is None or r.experiment == experiment]
    if not subset:
        return {"query_count": 0}
    totals = [r.total_ms for r in subset]
    emb = [r.query_embedding_ms for r in subset if r.query_embedding_ms is not None]
    sem = [r.semantic_search_ms for r in subset if r.semantic_search_ms is not None]
    kw = [r.keyword_search_ms for r in subset if r.keyword_search_ms is not None]
    rel = [r.relation_expansion_ms for r in subset if r.relation_expansion_ms is not None]
    return {
        "experiment": experiment or "ALL",
        "query_count": len(subset),
        "top1_primary_accuracy": _bool_rate(subset, "primary_hit_top1"),
        "hit_rate_at_3": _bool_rate(subset, "relevant_hit_top3"),
        "hit_rate_at_5": _bool_rate(subset, "relevant_hit_top5"),
        "primary_hit_rate_at_3": _bool_rate(subset, "primary_hit_top3"),
        "primary_hit_rate_at_5": _bool_rate(subset, "primary_hit_top5"),
        "mean_recall_at_3": _float_mean(subset, "set_recall_at_3"),
        "mean_recall_at_5": _float_mean(subset, "set_recall_at_5"),
        "primary_mean_recall_at_3": _float_mean(subset, "primary_set_recall_at_3"),
        "primary_mean_recall_at_5": _float_mean(subset, "primary_set_recall_at_5"),
        "mrr": _float_mean(subset, "reciprocal_rank"),
        "primary_mrr": _float_mean(subset, "primary_reciprocal_rank"),
        "column_hit_at_3": _bool_rate(subset, "column_hit_top3"),
        "column_hit_at_5": _bool_rate(subset, "column_hit_top5"),
        "column_mean_recall_at_3": _float_mean(subset, "column_set_recall_at_3"),
        "column_mean_recall_at_5": _float_mean(subset, "column_set_recall_at_5"),
        "column_mrr": _float_mean(subset, "column_mrr"),
        "relation_hit_rate": _bool_rate(subset, "relation_hit"),
        "relation_recall": _float_mean(subset, "relation_recall"),
        "avg_total_ms": mean(totals),
        "median_total_ms": median(totals),
        "p95_total_ms": percentile(totals, 95),
        "avg_query_embedding_ms": mean(emb) if emb else None,
        "avg_semantic_search_ms": mean(sem) if sem else None,
        "avg_keyword_search_ms": mean(kw) if kw else None,
        "avg_relation_expansion_ms": mean(rel) if rel else None,
    }


def category_summaries(rows: list[QueryEvalRow], experiment: str) -> list[dict[str, Any]]:
    by_cat: dict[str, list[QueryEvalRow]] = defaultdict(list)
    for r in rows:
        if r.experiment == experiment:
            by_cat[r.category].append(r)
    out = []
    for cat in sorted(by_cat):
        s = summarize_rows(by_cat[cat], experiment=experiment)
        s["category"] = cat
        out.append(s)
    return out


def ablation_deltas(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    by_name = {s["experiment"]: s for s in summaries}
    out: dict[str, Any] = {}

    def delta(a: str, b: str, metric: str) -> float | None:
        if a not in by_name or b not in by_name:
            return None
        return float(by_name[a].get(metric) or 0.0) - float(by_name[b].get(metric) or 0.0)

    out["semantic_expansion_hit5_delta"] = delta(
        "semantic_expansion", "semantic_no_expansion", "hit_rate_at_5"
    )
    out["semantic_expansion_mrr_delta"] = delta(
        "semantic_expansion", "semantic_no_expansion", "mrr"
    )
    out["hybrid_expansion_hit5_delta"] = delta(
        "hybrid_expansion", "hybrid_no_expansion", "hit_rate_at_5"
    )
    out["hybrid_expansion_mrr_delta"] = delta(
        "hybrid_expansion", "hybrid_no_expansion", "mrr"
    )
    out["hybrid_vs_semantic_hit5_delta"] = delta(
        "hybrid_expansion", "semantic_expansion", "hit_rate_at_5"
    )
    out["hybrid_vs_keyword_hit5_delta"] = delta(
        "hybrid_expansion", "keyword_no_expansion", "hit_rate_at_5"
    )
    return out


def deterministic_summary_text(summaries: list[dict[str, Any]], deltas: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if not summaries:
        return ["No evaluation summaries available."]
    ranked = sorted(summaries, key=lambda s: float(s.get("hit_rate_at_5") or 0.0), reverse=True)
    best = ranked[0]
    lines.append(
        f"{best['experiment']} recorded the highest Hit@5 "
        f"({float(best.get('hit_rate_at_5') or 0.0):.3f})."
    )
    mrr_ranked = sorted(summaries, key=lambda s: float(s.get("mrr") or 0.0), reverse=True)
    lines.append(
        f"{mrr_ranked[0]['experiment']} recorded the highest MRR "
        f"({float(mrr_ranked[0].get('mrr') or 0.0):.3f})."
    )
    if deltas.get("hybrid_expansion_hit5_delta") is not None:
        d = deltas["hybrid_expansion_hit5_delta"]
        lines.append(
            f"Hybrid expansion Hit@5 delta vs hybrid_no_expansion: {d:+.3f}."
        )
    if deltas.get("semantic_expansion_hit5_delta") is not None:
        d = deltas["semantic_expansion_hit5_delta"]
        lines.append(
            f"Semantic expansion Hit@5 delta vs semantic_no_expansion: {d:+.3f}."
        )
    return lines


def write_outputs(
    output_dir: Path,
    *,
    rows: list[QueryEvalRow],
    experiment_summaries: list[dict[str, Any]],
    category_rows: list[dict[str, Any]],
    metadata: dict[str, Any],
    deltas: dict[str, Any],
    summary_lines: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_payload = {
        "experiments": experiment_summaries,
        "categories": category_rows,
        "ablation_deltas": deltas,
        "notes": summary_lines,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    # summary.csv
    sum_fields = [
        "experiment",
        "query_count",
        "top1_primary_accuracy",
        "hit_rate_at_3",
        "hit_rate_at_5",
        "mean_recall_at_3",
        "mean_recall_at_5",
        "mrr",
        "primary_mrr",
        "column_hit_at_3",
        "column_hit_at_5",
        "relation_recall",
        "avg_total_ms",
        "median_total_ms",
        "p95_total_ms",
        "avg_query_embedding_ms",
        "avg_semantic_search_ms",
        "avg_keyword_search_ms",
        "avg_relation_expansion_ms",
    ]
    with (output_dir / "summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=sum_fields, extrasaction="ignore")
        w.writeheader()
        for s in experiment_summaries:
            w.writerow(s)

    # query_results.jsonl + csv
    with (output_dir / "query_results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")

    q_fields = [
        "query_id",
        "category",
        "query",
        "experiment",
        "matched_concepts",
        "top1_table",
        "top3_tables",
        "top5_tables",
        "primary_hit_top1",
        "relevant_hit_top3",
        "relevant_hit_top5",
        "first_relevant_rank",
        "reciprocal_rank",
        "column_hit_top3",
        "column_hit_top5",
        "relation_recall",
        "total_ms",
        "query_embedding_ms",
        "semantic_search_ms",
        "keyword_search_ms",
        "relation_expansion_ms",
    ]
    with (output_dir / "query_results.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=q_fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            d = asdict(r)
            d["matched_concepts"] = "|".join(r.matched_concepts)
            d["top3_tables"] = "|".join(r.top3_tables)
            d["top5_tables"] = "|".join(r.top5_tables)
            w.writerow(d)

    # failures.csv — Top5 relevant miss or primary top5 miss
    fail_fields = [
        "query_id",
        "query",
        "category",
        "experiment",
        "gold_primary",
        "gold_acceptable",
        "top5_returned",
        "matched_concepts",
        "expanded_terms",
        "reason",
    ]
    with (output_dir / "failures.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fail_fields)
        w.writeheader()
        for r in rows:
            reasons = []
            if not r.relevant_hit_top5:
                reasons.append("relevant_top5_miss")
            if not r.primary_hit_top5:
                reasons.append("primary_top5_miss")
            if not reasons:
                continue
            w.writerow(
                {
                    "query_id": r.query_id,
                    "query": r.query,
                    "category": r.category,
                    "experiment": r.experiment,
                    "gold_primary": "|".join(r.gold_primary),
                    "gold_acceptable": "|".join(r.gold_acceptable),
                    "top5_returned": "|".join(r.top5_tables),
                    "matched_concepts": "|".join(r.matched_concepts),
                    "expanded_terms": "|".join(r.expanded_terms),
                    "reason": "|".join(reasons),
                }
            )

    # category csv
    cat_fields = [
        "experiment",
        "category",
        "query_count",
        "top1_primary_accuracy",
        "hit_rate_at_3",
        "hit_rate_at_5",
        "mrr",
    ]
    with (output_dir / "category_summary.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cat_fields, extrasaction="ignore")
        w.writeheader()
        for s in category_rows:
            w.writerow(s)
