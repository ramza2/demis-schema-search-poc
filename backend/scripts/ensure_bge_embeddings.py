#!/usr/bin/env python3
from __future__ import annotations

import os

os.environ.setdefault("EMBEDDING_PROVIDER", "bge_m3")
os.environ.setdefault("EMBEDDING_MODEL_PATH", "/models/local/bge-m3")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

from app.core.config import get_settings
from app.db import session as session_mod
from app.embeddings.factory import get_embedding_provider
from app.services.embedding_service import EmbeddingService
from app.services.search.semantic import embedding_count


def main() -> None:
    get_settings.cache_clear()
    session_mod._engines.clear()
    session_mod._session_factories.clear()
    settings = get_settings()
    provider = get_embedding_provider(settings)
    print("provider", settings.embedding_provider, "model_key", provider.model_key)
    session = session_mod.get_catalog_session_factory()()
    try:
        cnt = embedding_count(session, provider.model_key)
        print("existing", cnt)
        if cnt == 0:
            result = EmbeddingService(session, settings=settings, provider=provider).run_embedding(
                "medical_demo"
            )
            print("run", result)
        print("final", embedding_count(session, provider.model_key))
    finally:
        session.close()


if __name__ == "__main__":
    main()
