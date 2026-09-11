"""Optional real BGE-M3 CPU smoke test.

Skipped unless RUN_BGE_M3_SMOKE=1.
Does not run in default pytest / CI.
"""

from __future__ import annotations

import os
import time

import pytest


@pytest.mark.skipif(os.getenv("RUN_BGE_M3_SMOKE") != "1", reason="Set RUN_BGE_M3_SMOKE=1 to run")
def test_bge_m3_cpu_smoke() -> None:
    os.environ["EMBEDDING_PROVIDER"] = "bge_m3"
    os.environ.setdefault("EMBEDDING_DEVICE", "cpu")
    # Prefer pre-downloaded local model (HF hub may be unreachable from containers).
    if not os.getenv("EMBEDDING_MODEL_PATH"):
        for candidate in (
            "/models/local/bge-m3",
            "/workspace/models/bge-m3",
            "models/bge-m3",
        ):
            if os.path.isdir(candidate):
                os.environ["EMBEDDING_MODEL_PATH"] = candidate
                break

    from app.core.config import get_settings
    from app.embeddings.factory import get_embedding_provider

    get_settings.cache_clear()
    settings = get_settings()
    provider = get_embedding_provider(settings)

    t0 = time.perf_counter()
    # First call triggers lazy model load.
    _ = provider.embed_texts(["warmup"])
    load_elapsed = time.perf_counter() - t0

    t1 = time.perf_counter()
    vectors = provider.embed_texts(
        [
            "Object Type: TABLE\nSchema: public\nTable: tb_lab_rst\n",
            "Object Type: COLUMN\nColumn: exm_cd\n",
        ]
    )
    embed_elapsed = time.perf_counter() - t1

    assert len(vectors) == 2
    assert all(len(v) == settings.embedding_dimension for v in vectors)
    assert provider.model_key
    assert settings.embedding_device == "cpu"
    print(
        f"BGE-M3 smoke ok: dim={settings.embedding_dimension} "
        f"device={settings.embedding_device} model_key={provider.model_key} "
        f"load+warmup={load_elapsed:.2f}s embed2={embed_elapsed:.2f}s"
    )
