"""Evaluation experiment definitions (search configs only; no ranking tuning)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Experiment:
    name: str
    mode: str
    expand_terms: bool
    expand_relations: bool
    max_relation_hops: int = 0
    evaluate_relation: bool = False


EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment(
        name="keyword_no_expansion",
        mode="keyword",
        expand_terms=False,
        expand_relations=False,
    ),
    Experiment(
        name="semantic_no_expansion",
        mode="semantic",
        expand_terms=False,
        expand_relations=False,
    ),
    Experiment(
        name="semantic_expansion",
        mode="semantic",
        expand_terms=True,
        expand_relations=False,
    ),
    Experiment(
        name="hybrid_no_expansion",
        mode="hybrid",
        expand_terms=False,
        expand_relations=False,
    ),
    Experiment(
        name="hybrid_expansion",
        mode="hybrid",
        expand_terms=True,
        expand_relations=False,
    ),
    Experiment(
        name="hybrid_expansion_relation",
        mode="hybrid",
        expand_terms=True,
        expand_relations=True,
        max_relation_hops=2,
        evaluate_relation=True,
    ),
)
