#!/usr/bin/env python3
"""Prepare pinned nlpai-lab/KoE5 weights for offline / air-gapped deploy.

Downloads a fixed revision, verifies model.safetensors SHA256, and writes
artifacts under a local directory (never commit weights to git).

Examples:
  python scripts/prepare_koe5_model.py
  python scripts/prepare_koe5_model.py --output /models/koe5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Allow running as `python scripts/prepare_koe5_model.py` from repo / backend.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.embeddings.koe5 import (  # noqa: E402
    KOE5_BASE_MODEL,
    KOE5_DEVELOPER,
    KOE5_DIMENSION,
    KOE5_LICENSE,
    KOE5_MAX_SEQ_LENGTH,
    KOE5_PINNED_REVISION,
    KOE5_REPO_ID,
    KOE5_SAFETENSORS_SHA256,
)

REQUIRED_ARTIFACTS = (
    "config.json",
    "modules.json",
    "tokenizer.json",
    "model.safetensors",
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def prepare(
    *,
    repo_id: str,
    revision: str,
    output: Path,
    expected_sha256: str,
) -> None:
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "huggingface_hub is required to prepare the model. "
            "Install backend dependencies first."
        ) from exc

    print(f"Downloading {repo_id}@{revision} -> {output}")
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(output),
        local_dir_use_symlinks=False,
    )

    missing = [name for name in REQUIRED_ARTIFACTS if not (output / name).is_file()]
    if missing:
        raise SystemExit(f"Missing required artifacts after download: {missing}")

    weights = output / "model.safetensors"
    actual = _sha256_file(weights)
    if actual != expected_sha256:
        raise SystemExit(
            "model.safetensors SHA256 mismatch:\n"
            f"  expected: {expected_sha256}\n"
            f"  actual:   {actual}"
        )

    manifest = {
        "model_name": repo_id,
        "developer": KOE5_DEVELOPER,
        "base_model": KOE5_BASE_MODEL,
        "license": KOE5_LICENSE,
        "revision": revision,
        "dimension": KOE5_DIMENSION,
        "max_seq_length": KOE5_MAX_SEQ_LENGTH,
        "model_safetensors_sha256": expected_sha256,
        "expected_local_path": "/models/koe5",
    }
    # Repo-root manifest (weights stay under models/ which is gitignored).
    repo_root = _BACKEND_ROOT.parent
    manifest_path = repo_root / "models" / "koe5.manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Verified model.safetensors SHA256={actual}")
    print(f"Wrote manifest {manifest_path}")
    print("Done. Offline load example:")
    print(f"  EMBEDDING_PROVIDER=koe5")
    print(f"  EMBEDDING_MODEL_NAME={repo_id}")
    print(f"  EMBEDDING_MODEL_PATH={output}")
    print(f"  EMBEDDING_MODEL_REVISION={revision}")
    print("  EMBEDDING_DIMENSION=1024")
    print("  EMBEDDING_MAX_SEQ_LENGTH=512")
    print("  EMBEDDING_NORMALIZE=true")
    print("  HF_HUB_OFFLINE=true")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare pinned KoE5 for offline use")
    parser.add_argument("--repo-id", default=KOE5_REPO_ID)
    parser.add_argument("--revision", default=KOE5_PINNED_REVISION)
    parser.add_argument(
        "--output",
        default=str(_BACKEND_ROOT.parent / "models" / "koe5"),
        help="Local directory for model weights (default: <repo>/models/koe5)",
    )
    parser.add_argument("--expected-sha256", default=KOE5_SAFETENSORS_SHA256)
    args = parser.parse_args()
    prepare(
        repo_id=args.repo_id,
        revision=args.revision,
        output=Path(args.output),
        expected_sha256=args.expected_sha256,
    )


if __name__ == "__main__":
    main()
