"""Evaluation reproducibility helpers (metadata only; no search changes)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any

# Weight / config files that identify a local sentence-transformers artifact.
_ARTIFACT_GLOBS = (
    "model.safetensors",
    "pytorch_model.bin",
    "model.onnx",
    "config.json",
    "modules.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "sentencepiece.bpe.model",
)


REQUIRED_METADATA_FIELDS = (
    "git_commit",
    "model_name",
    "model_key",
    "model_revision",
    "model_artifact_sha256",
    "terminology_dict_sha256",
    "gold_dataset_sha256",
    "schema_fingerprint",
)


def resolve_git_commit(*, repo_root: Path | None = None) -> str:
    """Resolve git commit for run_metadata.

    Priority:
    1. EVALUATION_GIT_COMMIT env
    2. git rev-parse HEAD (when .git is available)
    3. "unknown"
    """
    env = (os.environ.get("EVALUATION_GIT_COMMIT") or "").strip()
    if env:
        return env
    root = repo_root or Path(__file__).resolve().parents[3]
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if sha:
            return sha
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def resolve_model_revision(settings: Any) -> str:
    """Explicit revision string for metadata.

    Priority:
    1. EVALUATION_MODEL_REVISION env (evaluation recording override)
    2. EMBEDDING_MODEL_REVISION via Settings.embedding_model_revision
    3. \"default\"
    """
    env = (os.environ.get("EVALUATION_MODEL_REVISION") or "").strip()
    if env:
        return env
    rev = getattr(settings, "embedding_model_revision", None)
    if rev is None or str(rev).strip() == "":
        return "default"
    return str(rev).strip()


def compute_model_artifact_sha256(model_path: str | Path | None) -> str:
    """Deterministic hash of local model artifact files.

    Returns sha256 hex, or an ``unavailable: ...`` reason string when hashing
    is not possible. Never embeds filesystem path into model_key.
    """
    if model_path is None or str(model_path).strip() == "":
        return "unavailable: no local model path"
    root = Path(str(model_path)).expanduser()
    if not root.exists():
        return f"unavailable: path does not exist ({root.name})"
    if not root.is_dir():
        # Single file artifact
        h = hashlib.sha256()
        h.update(root.name.encode("utf-8"))
        h.update(b"\0")
        h.update(root.read_bytes())
        return h.hexdigest()

    entries: list[tuple[str, bytes]] = []
    for pattern in _ARTIFACT_GLOBS:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            file_hash = hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8")
            entries.append((rel, file_hash))

    # Also include any *.safetensors / *.bin at top level not covered above.
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".safetensors", ".bin", ".onnx"}:
            continue
        rel = path.name
        if any(rel == e[0] for e in entries):
            continue
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest().encode("utf-8")
        entries.append((rel, file_hash))

    if not entries:
        return "unavailable: no hashable weight/config files found"

    manifest = hashlib.sha256()
    for rel, file_hash in sorted(entries, key=lambda x: x[0]):
        manifest.update(rel.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(file_hash)
        manifest.update(b"\n")
    return manifest.hexdigest()


def resolve_model_artifact_sha256(settings: Any) -> str:
    path = getattr(settings, "embedding_model_path", None)
    return compute_model_artifact_sha256(path)


def validate_run_metadata(metadata: dict[str, Any]) -> list[str]:
    """Return missing/invalid required field messages (empty if ok)."""
    errors: list[str] = []
    for key in REQUIRED_METADATA_FIELDS:
        if key not in metadata:
            errors.append(f"missing field: {key}")
            continue
        value = metadata[key]
        if value is None or (isinstance(value, str) and value.strip() == ""):
            errors.append(f"empty field: {key}")
    # git_commit must never be null-like
    if metadata.get("git_commit") is None:
        errors.append("git_commit must not be null")
    return errors


def assert_run_metadata(metadata: dict[str, Any]) -> None:
    errors = validate_run_metadata(metadata)
    if errors:
        raise ValueError("invalid run_metadata: " + "; ".join(errors))
