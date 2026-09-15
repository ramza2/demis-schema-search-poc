"""API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.embeddings import router as embeddings_router
from app.api.health import router as health_router
from app.api.schema import router as schema_router
from app.api.search import router as search_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(schema_router)
api_router.include_router(embeddings_router)
api_router.include_router(search_router)
