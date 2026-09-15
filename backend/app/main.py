"""FastAPI application entrypoint (Step 3)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings
from app.db.catalog_bootstrap import ensure_catalog_schema


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Create catalog tables / default source / vector extension if needed.
    # Does not download or load embedding models (lazy load on embedding run).
    ensure_catalog_schema()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.3.0",
        description="Step 3: CPU-only Embedding Pipeline + pgvector",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "step": settings.current_step,
            "docs": "/docs",
            "health": "/health",
            "analyze": "/api/v1/schema/analyze",
            "embeddings_rebuild": "/api/v1/embeddings/documents/rebuild",
            "embeddings_run": "/api/v1/embeddings/run",
        }

    return app


app = create_app()
