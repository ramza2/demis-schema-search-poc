"""FastAPI application entrypoint (Step 1)."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Step 1: Foundation + Mock Medical DB health endpoints",
    )
    app.include_router(api_router)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "app": settings.app_name,
            "step": settings.current_step,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
