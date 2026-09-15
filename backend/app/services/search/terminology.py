"""Rule-based medical terminology expansion (no schema answer leakage).

Concept matching uses `triggers` only. After a concept is triggered,
`expansion_terms` may add broader recall terms (including generics).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings

_DEFAULT_TERMS_PATH = Path(__file__).resolve().parents[2] / "resources" / "medical_terms.json"
_TABLEISH_RE = re.compile(r"(?i)\b(tb_[a-z0-9_]+|[a-z0-9_]+_id)\b")
# Physical identifiers from medical_demo that must never appear in the dictionary.
_FORBIDDEN_PHYSICAL_NAMES = frozenset(
    {
        "tb_lab_rst",
        "tb_lab_mst",
        "tb_lab_ord",
        "tb_med_ord",
        "tb_dgn_hist",
        "tb_img_rpt",
        "tb_adm_hist",
        "tb_cln_doc",
        "tb_pt_mst",
        "tb_provider",
        "exm_cd",
        "exm_nm",
        "rst_val",
        "rst_num",
        "lab_ord_id",
        "lab_rst_id",
        "pt_no",
        "dgn_cd",
        "drug_cd",
    }
)


@dataclass(frozen=True)
class Concept:
    id: str
    label: str
    triggers: tuple[str, ...]
    expansion_terms: tuple[str, ...]


@dataclass
class ExpansionResult:
    matched_concepts: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    expanded_query: str = ""


def _is_korean_or_phrase(term: str) -> bool:
    """Korean text and multi-word phrases keep natural substring/phrase matching."""
    if any(ch.isspace() for ch in term):
        return True
    return bool(re.search(r"[가-힣]", term))


def _term_hits(term: str, query: str, query_lower: str) -> bool:
    """Match triggers without English substring false positives.

    Latin/alphanumeric tokens (AST, ALT, BUN, HbA1c, ...) require word boundaries.
    Korean expressions and whitespace phrases keep phrase matching.
    """
    term_l = term.lower()
    if not term_l:
        return False
    if _is_korean_or_phrase(term):
        return term_l in query_lower or bool(
            re.search(
                rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
                query,
            )
        )
    # English / numeric token triggers: independent token only.
    return bool(
        re.search(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])",
            query,
        )
    )


def _load_concepts(path: Path) -> list[Concept]:
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts: list[Concept] = []
    for item in data.get("concepts") or []:
        raw_triggers = list(item.get("triggers") or [])
        # Legacy aliases: treat as triggers+expansion only when triggers missing.
        if not raw_triggers and item.get("aliases"):
            raw_triggers = list(item.get("aliases") or [])
        if item.get("label"):
            raw_triggers.append(item["label"])
        triggers = tuple(dict.fromkeys(a.strip() for a in raw_triggers if a and str(a).strip()))

        raw_expansion = list(item.get("expansion_terms") or [])
        if not raw_expansion and item.get("aliases"):
            raw_expansion = list(item.get("aliases") or [])
        expansion = tuple(dict.fromkeys(a.strip() for a in raw_expansion if a and str(a).strip()))

        concepts.append(
            Concept(
                id=str(item["id"]),
                label=str(item.get("label") or item["id"]),
                triggers=triggers,
                expansion_terms=expansion,
            )
        )
    return concepts


@lru_cache
def get_concepts(path_str: str | None = None) -> tuple[Concept, ...]:
    path = Path(path_str) if path_str else _DEFAULT_TERMS_PATH
    return tuple(_load_concepts(path))


def clear_concept_cache() -> None:
    get_concepts.cache_clear()


def _all_dictionary_terms(concept: Concept) -> tuple[str, ...]:
    return tuple(dict.fromkeys((concept.label, *concept.triggers, *concept.expansion_terms)))


def assert_no_schema_leakage(concepts: tuple[Concept, ...] | None = None) -> list[str]:
    """Fail if dictionary contains physical table/column identifiers or answer mappings."""
    concepts = concepts or get_concepts()
    findings: list[str] = []
    for concept in concepts:
        for term in _all_dictionary_terms(concept):
            stripped = term.strip()
            lower = stripped.lower()
            if lower.startswith("tb_") or _TABLEISH_RE.fullmatch(stripped):
                findings.append(f"{concept.id}:tableish:{term}")
            if lower in _FORBIDDEN_PHYSICAL_NAMES:
                findings.append(f"{concept.id}:physical:{term}")
            if "->" in stripped or "→" in stripped:
                findings.append(f"{concept.id}:mapping:{term}")
            if re.search(r"(?i)\btable\s*[:=]", stripped) or re.search(
                r"(?i)\bcolumn\s*[:=]", stripped
            ):
                findings.append(f"{concept.id}:mapping:{term}")
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
        hit = any(_term_hits(trigger, normalized_query, query_lower) for trigger in concept.triggers)
        if not hit:
            continue
        matched.append(concept)
        for term in concept.expansion_terms:
            if not term:
                continue
            if term.lower() in query_lower:
                continue
            if term not in expanded:
                expanded.append(term)

    result.matched_concepts = [c.id for c in matched]
    result.expanded_terms = expanded
    if expanded:
        result.expanded_query = f"{normalized_query} " + " ".join(expanded)
    return result
