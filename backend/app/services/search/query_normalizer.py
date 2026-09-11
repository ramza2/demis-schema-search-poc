"""Deterministic query normalization (no LLM rewrite)."""

from __future__ import annotations

import re
from dataclasses import dataclass


_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedQuery:
    original: str
    normalized: str


def normalize_query(query: str) -> NormalizedQuery:
    original = query if query is not None else ""
    # Trim, collapse whitespace; lowercase Latin letters for case-insensitive match.
    text = original.strip()
    text = _WS_RE.sub(" ", text)

    def _lower_latin(match: re.Match[str]) -> str:
        return match.group(0).lower()

    normalized = re.sub(r"[A-Za-z]+", _lower_latin, text)
    return NormalizedQuery(original=original, normalized=normalized)
