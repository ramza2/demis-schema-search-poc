"""Rule-based medical terminology expansion (no schema answer leakage)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings

_DEFAULT_TERMS_PATH = Path(__file__).resolve().parents[2] / "resources" / "medical_terms.json"
_TABLEISH_RE = re.compile(r"(?i)\b(tb_[a-z0-9_]+|[a-z0-9_]+_id)\b")


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    aliases: tuple[str, ...]


@dataclass
class ExpansionResult:
    matched_concepts: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    expanded_query: str = ""


def _load_concepts(path: Path) -> list[Concept]:
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts: list[Concept] = []
    for item in data.get("concepts") or []:
        raw_aliases = list(item.get("aliases") or [])
        if item.get("label"):
            raw_aliases.append(item["label"])
        aliases = tuple(dict.fromkeys(a.strip() for a in raw_aliases if a and str(a).strip()))
        concepts.append(
            Concept(
                id=str(item["id"]),
                label=str(item.get("label") or item["id"]),
                aliases=aliases,
            )
        )
    return concepts


@lru_cache
def get_concepts(path_str: str | None = None) -> tuple[Concept, ...]:
    path = Path(path_str) if path_str else _DEFAULT_TERMS_PATH
    return tuple(_load_concepts(path))


def clear_concept_cache() -> None:
    get_concepts.cache_clear()


def assert_no_schema_leakage(concepts: tuple[Concept, ...] | None = None) -> list[str]:
    concepts = concepts or get_concepts()
    findings: list[str] = []
    for concept in concepts:
        for alias in (concept.label, *concept.aliases):
            if alias.lower().startswith("tb_") or _TABLEISH_RE.fullmatch(alias.strip()):
                findings.append(f"{concept.id}:{alias}")
    return findings


def expand_query(
    normalized_query: str,
    *,
    settings: Settings | None = None,
    enabled: bool = True,
) -> ExpansionResult:
    cfg = settings or get_settings()
    result = ExpansionResult(expanded_query=normalized_query)
    if not enabled or not (normalized_query or "").strip():
        return result

    concepts = get_concepts(cfg.medical_terms_path)
    query_lower = normalized_query.lower()
    matched: list[Concept] = []
    expanded: list[str] = []

    for concept in concepts:
        hit = False
        for alias in concept.aliases:
            alias_l = alias.lower()
            if not alias_l:
                continue
            if alias_l in query_lower or re.search(
                rf"(?i)(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])",
                normalized_query,
            ):
                hit = True
                break
        if hit:
            matched.append(concept)
            for alias in concept.aliases:
                if alias and alias.lower() not in query_lower and alias not in expanded:
                    expanded.append(alias)

    result.matched_concepts = [c.id for c in matched]
    result.expanded_terms = expanded
    if expanded:
        result.expanded_query = f"{normalized_query} " + " ".join(expanded)
    return result
