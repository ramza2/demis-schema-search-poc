"""Unit tests for KoE5 provider (no real model weights required)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.embeddings.errors import ConfigurationError, DimensionMismatchError
from app.embeddings.factory import get_embedding_provider
from app.embeddings.koe5 import (
    KOE5_DIMENSION,
    KOE5_DOCUMENT_PREFIX,
    KOE5_PINNED_REVISION,
    KOE5_PREFIX_POLICY,
    KOE5_QUERY_PREFIX,
    KOE5_REPO_ID,
    KOE5_SAFETENSORS_SHA256,
    Koe5EmbeddingProvider,
    apply_e5_prefix,
    build_koe5_model_key,
)


def test_apply_e5_prefix_adds_once() -> None:
    assert apply_e5_prefix("간수치", KOE5_QUERY_PREFIX) == "query: 간수치"
    assert apply_e5_prefix("query: 간수치", KOE5_QUERY_PREFIX) == "query: 간수치"
    assert apply_e5_prefix("passage: doc", KOE5_DOCUMENT_PREFIX) == "passage: doc"
    assert apply_e5_prefix("tb_lab_rst", KOE5_DOCUMENT_PREFIX) == "passage: tb_lab_rst"


def test_build_koe5_model_key_excludes_path_and_includes_prefix_policy() -> None:
    key = build_koe5_model_key(
        model_name=KOE5_REPO_ID,
        revision=KOE5_PINNED_REVISION,
        dimension=1024,
        normalize=True,
        max_seq_length=512,
    )
    assert key.startswith(f"provider=koe5|model={KOE5_REPO_ID}|")
    assert f"rev={KOE5_PINNED_REVISION}" in key
    assert "dim=1024" in key
    assert "norm=true" in key
    assert "maxlen=512" in key
    assert f"prefix={KOE5_PREFIX_POLICY}" in key
    assert "/models/" not in key
    assert "path=" not in key


def test_settings_build_model_key_for_koe5() -> None:
    settings = Settings(
        embedding_provider="koe5",
        embedding_model_name=KOE5_REPO_ID,
        embedding_model_path="/models/koe5",
        embedding_model_revision=KOE5_PINNED_REVISION,
        embedding_dimension=1024,
        embedding_max_seq_length=512,
        embedding_normalize=True,
    )
    key = settings.build_model_key()
    assert "provider=koe5" in key
    assert "/models/koe5" not in key
    assert KOE5_PREFIX_POLICY in key


def test_factory_selects_koe5() -> None:
    settings = Settings(
        embedding_provider="koe5",
        embedding_model_name=KOE5_REPO_ID,
        embedding_model_path="/models/koe5",
        embedding_model_revision=KOE5_PINNED_REVISION,
        embedding_max_seq_length=512,
        hf_hub_offline=True,
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, Koe5EmbeddingProvider)
    assert provider.dimension == KOE5_DIMENSION


def test_offline_missing_path_raises_configuration_error() -> None:
    provider = Koe5EmbeddingProvider(
        model_path="/nonexistent/koe5",
        hf_hub_offline=True,
    )
    with pytest.raises(ConfigurationError, match="EMBEDDING_MODEL_PATH|local"):
        provider.embed_queries(["x"])


def test_dimension_mismatch_on_init() -> None:
    with pytest.raises(ConfigurationError, match="dimension"):
        Koe5EmbeddingProvider(dimension=768)


def test_query_and_passage_prefixes_and_no_double_application(tmp_path: Path) -> None:
    model_dir = tmp_path / "koe5"
    model_dir.mkdir()

    captured: dict[str, list[str]] = {}

    class _FakeST:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.max_seq_length = 512

        def encode(self, batch, **kwargs):  # noqa: ANN001, ANN003
            captured.setdefault("batches", []).extend(list(batch))

            class _Row(list):
                def tolist(self):  # noqa: ANN201
                    return list(self)

            class _Arr(list):
                pass

            return _Arr([_Row([1.0] * KOE5_DIMENSION) for _ in batch])

    fake_mod = MagicMock()
    fake_mod.SentenceTransformer = _FakeST
    provider = Koe5EmbeddingProvider(
        model_path=str(model_dir),
        hf_hub_offline=True,
        normalize=True,
    )
    with patch.dict("sys.modules", {"sentence_transformers": fake_mod}):
        q = provider.embed_queries(["간수치 검사"])
        d = provider.embed_documents(["Object Type: TABLE"])
        provider.embed_queries(["query: already"])
        provider.embed_documents(["passage: already"])

    assert len(q[0]) == KOE5_DIMENSION
    assert len(d[0]) == KOE5_DIMENSION
    assert captured["batches"][0] == "query: 간수치 검사"
    assert captured["batches"][1] == "passage: Object Type: TABLE"
    assert captured["batches"][2] == "query: already"
    assert captured["batches"][3] == "passage: already"


def test_dimension_validation_from_encode(tmp_path: Path) -> None:
    model_dir = tmp_path / "koe5"
    model_dir.mkdir()

    class _BadST:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            self.max_seq_length = 512

        def encode(self, batch, **kwargs):  # noqa: ANN001, ANN003
            class _Row(list):
                def tolist(self):  # noqa: ANN201
                    return list(self)

            class _Arr(list):
                pass

            return _Arr([_Row([1.0] * 8) for _ in batch])

    fake_mod = MagicMock()
    fake_mod.SentenceTransformer = _BadST
    provider = Koe5EmbeddingProvider(model_path=str(model_dir), hf_hub_offline=True)
    with patch.dict("sys.modules", {"sentence_transformers": fake_mod}):
        with pytest.raises(DimensionMismatchError):
            provider.embed_texts(["x"])


def test_safetensors_sha_constant() -> None:
    assert len(KOE5_SAFETENSORS_SHA256) == 64
    assert KOE5_SAFETENSORS_SHA256 == (
        "97693a2aeaeae9ecaac5fc68c5d27007dd1604d667ccbc61a32a52a9035cca67"
    )


def test_official_eval_allows_koe5() -> None:
    from app.evaluation.runner import assert_official_provider

    assert_official_provider(Settings(embedding_provider="koe5"))
