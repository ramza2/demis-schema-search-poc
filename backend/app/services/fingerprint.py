"""Deterministic fingerprint helpers for schema catalog objects."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canonical(v) for v in value]
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    return value


def fingerprint(payload: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON (stable key order, no timestamps)."""
    encoded = json.dumps(_canonical(payload), ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
