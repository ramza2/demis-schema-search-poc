"""FastAPI application entrypoint (Step 3)."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.target_connection import HOST_VALIDATION_MESSAGE


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
        version="0.4.0",
        description="Step 4: Semantic/Keyword Hybrid Schema Search + Terminology + FK Expansion",
        lifespan=lifespan,
    )
    app.include_router(api_router)

    @app.exception_handler(RequestValidationError)
    async def _host_validation_as_400(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Map Target Host validation failures to HTTP 400 with a clear message."""
        for err in exc.errors():
            msg = str(err.get("msg") or "")
            loc = err.get("loc") or ()
            if HOST_VALIDATION_MESSAGE in msg and "host" in {str(x) for x in loc}:
                return JSONResponse(
                    status_code=400,
                    content={"detail": HOST_VALIDATION_MESSAGE},
                )
        # Match FastAPI's default validation handler behavior: Pydantic v2 may
        # include non-JSON-serializable objects (for example ValueError) under
        # ctx.error for model-validator failures.
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(exc.errors())},
        )

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
            "schema_search": "/api/v1/search/schema",
        }

    return app


app = create_app()
