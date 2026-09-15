"""Step 5.1 evaluation reproducibility unit tests (metadata only)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.evaluation.reproducibility import (
    REQUIRED_METADATA_FIELDS,
    assert_run_metadata,
    compute_model_artifact_sha256,
    resolve_git_commit,
    resolve_model_artifact_sha256,
    resolve_model_revision,
    validate_run_metadata,
)


def test_explicit_git_commit_env_overrides_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALUATION_GIT_COMMIT", "abc123deadbeef")
    assert resolve_git_commit() == "abc123deadbeef"


def test_git_commit_falls_back_to_unknown_without_git(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("EVALUATION_GIT_COMMIT", raising=False)
    # Empty directory has no .git; git rev-parse fails → unknown
    assert resolve_git_commit(repo_root=tmp_path) == "unknown"


def test_model_key_identical_for_different_local_paths() -> None:
    a = Settings(
        embedding_model_name="BAAI/bge-m3",
        embedding_model_path="/models/local/path-a",
        embedding_model_revision="default",
        embedding_dimension=1024,
        embedding_normalize=True,
        embedding_max_seq_length=1024,
    )
    b = Settings(
        embedding_model_name="BAAI/bge-m3",
        embedding_model_path="/models/local/path-b",
        embedding_model_revision="default",
        embedding_dimension=1024,
        embedding_normalize=True,
        embedding_max_seq_length=1024,
    )
    assert a.build_model_key() == b.build_model_key()
    assert "path-a" not in a.build_model_key()
    assert "path-b" not in b.build_model_key()
    assert a.build_model_key().startswith("BAAI/bge-m3|")


def test_model_artifact_hash_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "bge-m3"
    root.mkdir()
    (root / "config.json").write_text('{"arch":"x"}', encoding="utf-8")
    (root / "model.safetensors").write_bytes(b"weight-bytes-v1")
    (root / "modules.json").write_text("[]", encoding="utf-8")

    h1 = compute_model_artifact_sha256(root)
    h2 = compute_model_artifact_sha256(str(root))
    assert len(h1) == 64
    assert h1 == h2
    assert not h1.startswith("unavailable:")

    # Same content under a different directory name → same hash (path not embedded)
    other = tmp_path / "other-copy"
    other.mkdir()
    (other / "config.json").write_text('{"arch":"x"}', encoding="utf-8")
    (other / "model.safetensors").write_bytes(b"weight-bytes-v1")
    (other / "modules.json").write_text("[]", encoding="utf-8")
    assert compute_model_artifact_sha256(other) == h1


def test_model_artifact_unavailable_without_path() -> None:
    settings = SimpleNamespace(embedding_model_path=None)
    assert resolve_model_artifact_sha256(settings).startswith("unavailable:")


def test_model_revision_from_evaluation_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVALUATION_MODEL_REVISION", "hf-rev-deadbeef")
    settings = Settings(embedding_model_revision=None)
    assert resolve_model_revision(settings) == "hf-rev-deadbeef"


def test_model_revision_from_settings_when_env_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVALUATION_MODEL_REVISION", raising=False)
    settings = Settings(embedding_model_revision="main")
    assert resolve_model_revision(settings) == "main"


def test_run_metadata_required_fields_present() -> None:
    metadata = {
        "git_commit": "unknown",
        "model_name": "BAAI/bge-m3",
        "model_key": "BAAI/bge-m3|rev=default|dim=1024|norm=true|maxlen=1024",
        "model_revision": "default",
        "model_artifact_sha256": "unavailable: no local model path",
        "terminology_dict_sha256": "a" * 64,
        "gold_dataset_sha256": "b" * 64,
        "schema_fingerprint": "c" * 64,
    }
    assert validate_run_metadata(metadata) == []
    assert_run_metadata(metadata)
    for key in REQUIRED_METADATA_FIELDS:
        assert key in metadata


def test_run_metadata_rejects_null_git_commit() -> None:
    metadata = {
        "git_commit": None,
        "model_name": "BAAI/bge-m3",
        "model_key": "k",
        "model_revision": "default",
        "model_artifact_sha256": "unavailable: x",
        "terminology_dict_sha256": "a" * 64,
        "gold_dataset_sha256": "b" * 64,
        "schema_fingerprint": "c" * 64,
    }
    errs = validate_run_metadata(metadata)
    assert any("git_commit" in e for e in errs)
    with pytest.raises(ValueError):
        assert_run_metadata(metadata)


def test_run_metadata_rejects_missing_artifact_field() -> None:
    metadata = {
        "git_commit": "abc",
        "model_name": "BAAI/bge-m3",
        "model_key": "k",
        "model_revision": "default",
        "terminology_dict_sha256": "a" * 64,
        "gold_dataset_sha256": "b" * 64,
        "schema_fingerprint": "c" * 64,
    }
    errs = validate_run_metadata(metadata)
    assert any("model_artifact_sha256" in e for e in errs)
