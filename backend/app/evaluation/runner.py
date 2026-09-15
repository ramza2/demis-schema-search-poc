"""CLI evaluation runner for Step 5 Gold Set quantitative evaluation.

Does not modify search ranking. Calls SchemaSearchService as-is.
Official runs require EMBEDDING_PROVIDER=bge_m3.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import Settings, get_settings
from app.db.session import get_catalog_session_factory
from app.embeddings.factory import get_embedding_provider
from app.evaluation.experiments import EXPERIMENTS, Experiment
from app.evaluation.gold import GoldDataset, assert_valid_gold, load_gold_dataset
from app.evaluation.metrics import (
    extract_column_candidates,
    extract_relation_tables,
    extract_table_candidates,
    first_relevant_rank,
    hit_at_k,
    reciprocal_rank,
    relation_hit,
    relation_recall,
    set_recall_at_k,
    top1_primary_accuracy,
    top_k_identities,
)
from app.evaluation.report import (
    QueryEvalRow,
    ablation_deltas,
    category_summaries,
    deterministic_summary_text,
    summarize_rows,
    write_outputs,
)
from app.evaluation.reproducibility import (
    assert_run_metadata,
    resolve_git_commit,
    resolve_model_artifact_sha256,
    resolve_model_revision,
)
from app.services.search.search_service import SchemaSearchService, SearchError
from app.services.search.semantic import embedding_count
from app.services.search.terminology import clear_concept_cache, get_concepts


DEFAULT_GOLD = Path(__file__).resolve().parents[2] / "evaluation" / "gold_schema_queries.json"


class OfficialEvaluationError(RuntimeError):
    pass


def _dict_hash() -> str:
    clear_concept_cache()
    concepts = get_concepts()
    blob = "|".join(
        f"{c.id}:{','.join(c.triggers)}::{','.join(c.expansion_terms)}" for c in concepts
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _schema_fingerprint(session) -> str:
    try:
        from sqlalchemy import text

        row = session.execute(
            text(
                "SELECT coalesce(max(schema_fingerprint), '') FROM catalog_analysis_run "
                "WHERE status = 'SUCCESS'"
            )
        ).scalar()
        value = str(row or "").strip()
        if value:
            return value
        return "unavailable: no successful analysis fingerprint"
    except Exception as exc:  # noqa: BLE001
        return f"unavailable: {type(exc).__name__}"

def assert_official_provider(settings: Settings) -> None:
    provider = (settings.embedding_provider or "").strip().lower()
    if provider != "bge_m3":
        raise OfficialEvaluationError(
            f"Official evaluation requires EMBEDDING_PROVIDER=bge_m3, got {provider!r}. "
            "Fake provider is allowed only in unit tests."
        )


def evaluate_query_result(
    *,
    gold_query,
    experiment: Experiment,
    search_result,
) -> QueryEvalRow:
    """Score one search result without mutating result order."""
    direct = list(search_result.direct_results)
    related = list(search_result.related_tables)
    table_cands = extract_table_candidates(direct)
    col_cands = extract_column_candidates(direct)
    primary = gold_query.gold.primary_tables
    relevant = gold_query.gold.relevant_tables
    gold_cols = gold_query.gold.relevant_columns
    gold_rels = gold_query.gold.relation_tables

    first_rel = first_relevant_rank(table_cands, relevant)
    first_pri = first_relevant_rank(table_cands, primary)

    col_hit3 = col_hit5 = None
    col_rec3 = col_rec5 = col_mrr = None
    if gold_cols:
        col_hit3 = hit_at_k(col_cands, gold_cols, 3)
        col_hit5 = hit_at_k(col_cands, gold_cols, 5)
        col_rec3 = set_recall_at_k(col_cands, gold_cols, 3)
        col_rec5 = set_recall_at_k(col_cands, gold_cols, 5)
        col_mrr = reciprocal_rank(first_relevant_rank(col_cands, gold_cols))

    rel_hit = rel_rec = None
    if experiment.evaluate_relation and gold_rels:
        found = extract_relation_tables(direct, related)
        rel_hit = relation_hit(found, gold_rels)
        rel_rec = relation_recall(found, gold_rels)

    timings = search_result.timings or {}
    return QueryEvalRow(
        query_id=gold_query.id,
        category=gold_query.category,
        query=gold_query.query,
        experiment=experiment.name,
        matched_concepts=list(search_result.matched_concepts or []),
        expanded_terms=list(search_result.expanded_terms or []),
        top1_table=table_cands[0].identity if table_cands else None,
        top3_tables=top_k_identities(table_cands, 3),
        top5_tables=top_k_identities(table_cands, 5),
        primary_hit_top1=top1_primary_accuracy(table_cands, primary),
        relevant_hit_top3=hit_at_k(table_cands, relevant, 3),
        relevant_hit_top5=hit_at_k(table_cands, relevant, 5),
        primary_hit_top3=hit_at_k(table_cands, primary, 3),
        primary_hit_top5=hit_at_k(table_cands, primary, 5),
        set_recall_at_3=set_recall_at_k(table_cands, relevant, 3),
        set_recall_at_5=set_recall_at_k(table_cands, relevant, 5),
        primary_set_recall_at_3=set_recall_at_k(table_cands, primary, 3),
        primary_set_recall_at_5=set_recall_at_k(table_cands, primary, 5),
        first_relevant_rank=first_rel,
        reciprocal_rank=reciprocal_rank(first_rel),
        primary_first_rank=first_pri,
        primary_reciprocal_rank=reciprocal_rank(first_pri),
        column_hit_top3=col_hit3,
        column_hit_top5=col_hit5,
        column_set_recall_at_3=col_rec3,
        column_set_recall_at_5=col_rec5,
        column_mrr=col_mrr,
        relation_hit=rel_hit,
        relation_recall=rel_rec,
        total_ms=float(search_result.elapsed_ms or timings.get("total_ms") or 0.0),
        query_embedding_ms=_opt_float(timings.get("query_embedding_ms")),
        semantic_search_ms=_opt_float(timings.get("semantic_search_ms")),
        keyword_search_ms=_opt_float(timings.get("keyword_search_ms")),
        relation_expansion_ms=_opt_float(timings.get("relation_expansion_ms")),
        gold_primary=list(primary),
        gold_acceptable=list(gold_query.gold.acceptable_tables),
        gold_columns=list(gold_cols),
        gold_relation_tables=list(gold_rels),
    )


def _opt_float(v) -> float | None:
    if v is None:
        return None
    return float(v)


def run_evaluation(
    *,
    gold_path: Path,
    output_dir: Path,
    top_k: int = 10,
    allow_fake: bool = False,
    experiments: tuple[Experiment, ...] | None = None,
    warmup: bool = True,
) -> Path:
    settings = get_settings()
    if not allow_fake:
        assert_official_provider(settings)

    session = get_catalog_session_factory()()
    try:
        dataset = load_gold_dataset(gold_path)
        assert_valid_gold(dataset, session=session)

        provider = get_embedding_provider(settings)
        model_key = provider.model_key
        needs_semantic = any(e.mode in {"semantic", "hybrid"} for e in (experiments or EXPERIMENTS))
        if needs_semantic:
            cnt = embedding_count(session, model_key)
            if cnt == 0:
                raise OfficialEvaluationError(
                    f"No embeddings for model_key={model_key}. "
                    "Run POST /api/v1/embeddings/run first."
                )

        service = SchemaSearchService(session, settings=settings, provider=provider)
        exps = experiments or EXPERIMENTS

        if warmup and needs_semantic:
            # Warm-up excluded from latency stats.
            try:
                service.search(
                    query="warmup query for embedding",
                    mode="semantic",
                    top_k=3,
                    expand_terms=False,
                    expand_relations_enabled=False,
                )
            except SearchError:
                pass

        rows: list[QueryEvalRow] = []
        for exp in exps:
            for gq in dataset.queries:
                result = service.search(
                    query=gq.query,
                    mode=exp.mode,
                    top_k=top_k,
                    expand_terms=exp.expand_terms,
                    expand_relations_enabled=exp.expand_relations,
                    max_relation_hops=exp.max_relation_hops if exp.expand_relations else 0,
                )
                rows.append(
                    evaluate_query_result(
                        gold_query=gq,
                        experiment=exp,
                        search_result=result,
                    )
                )

        experiment_summaries = [summarize_rows(rows, experiment=e.name) for e in exps]
        cat_rows: list[dict] = []
        for e in exps:
            cat_rows.extend(category_summaries(rows, e.name))
        deltas = ablation_deltas(experiment_summaries)
        notes = deterministic_summary_text(experiment_summaries, deltas)

        metadata = {
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": resolve_git_commit(),
            "model_name": settings.embedding_model_name,
            "model_key": model_key,
            "model_revision": resolve_model_revision(settings),
            "model_artifact_sha256": resolve_model_artifact_sha256(settings),
            "embedding_model_path_configured": bool(
                (settings.embedding_model_path or "").strip()
            ),
            "embedding_dimension": settings.embedding_dimension,
            "normalize": settings.embedding_normalize,
            "max_seq_length": settings.embedding_max_seq_length,
            "embedding_provider": settings.embedding_provider,
            "rrf_k": settings.search_rrf_k,
            "candidate_multiplier": settings.search_candidate_multiplier,
            "candidate_min": settings.search_candidate_min,
            "terminology_dict_sha256": _dict_hash(),
            "gold_dataset_path": str(gold_path),
            "gold_dataset_sha256": dataset.content_hash,
            "gold_version": dataset.version,
            "query_count": len(dataset.queries),
            "experiments": [e.name for e in exps],
            "python_version": sys.version,
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "schema_fingerprint": _schema_fingerprint(session),
            "top_k": top_k,
            "warmup": warmup,
            "allow_fake": allow_fake,
        }
        assert_run_metadata(metadata)

        write_outputs(
            output_dir,
            rows=rows,
            experiment_summaries=experiment_summaries,
            category_rows=cat_rows,
            metadata=metadata,
            deltas=deltas,
            summary_lines=notes,
        )
        return output_dir
    finally:
        session.close()


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Step 5 Gold Set schema search evaluation runner")
    p.add_argument(
        "--gold",
        type=Path,
        default=Path(os.environ.get("GOLD_DATASET_PATH", str(DEFAULT_GOLD))),
        help="Path to gold_schema_queries.json",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output directory (default: evaluation/results/<timestamp>)",
    )
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument(
        "--allow-fake",
        action="store_true",
        help="Allow fake embedding provider (unit/dev only; not official)",
    )
    p.add_argument("--no-warmup", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    get_settings.cache_clear()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    default_out = Path(__file__).resolve().parents[2] / "evaluation" / "results" / ts
    output = args.output or default_out
    try:
        out = run_evaluation(
            gold_path=args.gold,
            output_dir=output,
            top_k=args.top_k,
            allow_fake=args.allow_fake,
            warmup=not args.no_warmup,
        )
    except OfficialEvaluationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(f"Evaluation complete: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
