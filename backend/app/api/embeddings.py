"""Embedding / Search Document APIs (Step 3 — no semantic search)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.catalog_bootstrap import ensure_catalog_schema
from app.db.session import get_catalog_session_factory
from app.embeddings.factory import get_embedding_provider
from app.models.catalog import (
    CatalogEmbedding,
    CatalogEmbeddingRun,
    CatalogSearchDocument,
    CatalogSource,
)
from app.schemas.embedding_api import (
    DocumentRebuildResponse,
    EmbeddingRunResponse,
    EmbeddingRunSummary,
    EmbeddingStatsResponse,
    SearchDocumentDetail,
    SearchDocumentSummary,
)
from app.services.embedding_service import EmbeddingService, sanitize_error_message

router = APIRouter(prefix="/api/v1/embeddings", tags=["embeddings"])


def _session():
    ensure_catalog_schema()
    return get_catalog_session_factory()()


def _resolve_source_filter(
    session,
    *,
    source_id: int | None,
    source_name: str | None,
) -> tuple[int | None, str | None]:
    """Resolve optional source filter. Both omitted → no filter (backward compatible)."""
    if source_id is not None:
        source = session.get(CatalogSource, int(source_id))
        if source is None:
            raise HTTPException(status_code=404, detail=f"source_id={source_id} not found")
        return int(source.id), source.source_name
    if source_name and source_name.strip():
        source = session.scalar(
            select(CatalogSource).where(CatalogSource.source_name == source_name.strip())
        )
        if source is None:
            raise HTTPException(
                status_code=404, detail=f"source_name={source_name!r} not found"
            )
        return int(source.id), source.source_name
    return None, None


@router.post("/documents/rebuild", response_model=DocumentRebuildResponse)
def rebuild_documents(source: str = Query(default="medical_demo")) -> DocumentRebuildResponse:
    session = _session()
    try:
        service = EmbeddingService(session)
        stats = service.rebuild_documents(source_name=source)
        return DocumentRebuildResponse(
            source=stats.source,
            tables=stats.tables,
            columns=stats.columns,
            documents=stats.documents,
            created=stats.created,
            updated=stats.updated,
            unchanged=stats.unchanged,
            deactivated=stats.deactivated,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=sanitize_error_message(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=sanitize_error_message(f"{type(exc).__name__}")
        ) from exc
    finally:
        session.close()


@router.post("/run", response_model=EmbeddingRunResponse)
def run_embedding(source: str = Query(default="medical_demo")) -> EmbeddingRunResponse:
    session = _session()
    try:
        service = EmbeddingService(session)
        result = service.run_embedding(source_name=source)
        return EmbeddingRunResponse(
            run_id=result.run_id,
            status=result.status,
            model_key=result.model_key,
            documents=result.documents,
            embedded=result.embedded,
            skipped=result.skipped,
            failed=result.failed,
            started_at=result.started_at,
            finished_at=result.finished_at,
            error_message=result.error_message,
            error_code=result.error_code,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=sanitize_error_message(str(exc))) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=sanitize_error_message(f"{type(exc).__name__}")
        ) from exc
    finally:
        session.close()


@router.get("/runs", response_model=list[EmbeddingRunSummary])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    source_id: int | None = Query(default=None),
    source_name: str | None = Query(default=None),
) -> list[EmbeddingRunSummary]:
    session = _session()
    try:
        resolved_id, _ = _resolve_source_filter(
            session, source_id=source_id, source_name=source_name
        )
        stmt = select(CatalogEmbeddingRun).order_by(CatalogEmbeddingRun.id.desc()).limit(limit)
        if resolved_id is not None:
            stmt = stmt.where(CatalogEmbeddingRun.source_id == resolved_id)
        rows = session.scalars(stmt).all()
        return [
            EmbeddingRunSummary(
                id=r.id,
                source_id=r.source_id,
                status=r.status,
                model_key=r.model_key,
                started_at=r.started_at,
                finished_at=r.finished_at,
                document_count=r.document_count,
                embedded_count=r.embedded_count,
                skipped_count=r.skipped_count,
                failed_count=r.failed_count,
                error_message=r.error_message,
                error_code=r.error_code,
            )
            for r in rows
        ]
    finally:
        session.close()


@router.get("/runs/{run_id}", response_model=EmbeddingRunSummary)
def get_run(run_id: int) -> EmbeddingRunSummary:
    session = _session()
    try:
        run = session.get(CatalogEmbeddingRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="embedding run not found")
        return EmbeddingRunSummary(
            id=run.id,
            source_id=run.source_id,
            status=run.status,
            model_key=run.model_key,
            started_at=run.started_at,
            finished_at=run.finished_at,
            document_count=run.document_count,
            embedded_count=run.embedded_count,
            skipped_count=run.skipped_count,
            failed_count=run.failed_count,
            error_message=run.error_message,
            error_code=run.error_code,
        )
    finally:
        session.close()


@router.get("/stats", response_model=EmbeddingStatsResponse)
def embedding_stats(
    source_id: int | None = Query(default=None),
    source_name: str | None = Query(default=None),
) -> EmbeddingStatsResponse:
    session = _session()
    cfg = get_settings()
    try:
        resolved_id, resolved_name = _resolve_source_filter(
            session, source_id=source_id, source_name=source_name
        )
        doc_filters = [CatalogSearchDocument.active.is_(True)]
        if resolved_id is not None:
            doc_filters.append(CatalogSearchDocument.source_id == resolved_id)

        active_documents = int(
            session.scalar(
                select(func.count()).select_from(CatalogSearchDocument).where(*doc_filters)
            )
            or 0
        )
        table_documents = int(
            session.scalar(
                select(func.count())
                .select_from(CatalogSearchDocument)
                .where(*doc_filters, CatalogSearchDocument.object_type == "TABLE")
            )
            or 0
        )
        column_documents = int(
            session.scalar(
                select(func.count())
                .select_from(CatalogSearchDocument)
                .where(*doc_filters, CatalogSearchDocument.object_type == "COLUMN")
            )
            or 0
        )

        emb_stmt = select(func.count()).select_from(CatalogEmbedding)
        if resolved_id is not None:
            emb_stmt = emb_stmt.join(
                CatalogSearchDocument,
                CatalogSearchDocument.id == CatalogEmbedding.search_document_id,
            ).where(CatalogSearchDocument.source_id == resolved_id)
        embedding_count = int(session.scalar(emb_stmt) or 0)

        model_key_stmt = select(CatalogEmbedding.model_key).distinct()
        if resolved_id is not None:
            model_key_stmt = model_key_stmt.join(
                CatalogSearchDocument,
                CatalogSearchDocument.id == CatalogEmbedding.search_document_id,
            ).where(CatalogSearchDocument.source_id == resolved_id)
        model_keys = list(session.scalars(model_key_stmt).all())

        # Stale: active docs whose fingerprint does not match embedding for current model_key.
        provider = get_embedding_provider(cfg)
        current_key = provider.model_key
        active_docs = session.scalars(
            select(CatalogSearchDocument).where(*doc_filters)
        ).all()
        emb_query = select(CatalogEmbedding).where(CatalogEmbedding.model_key == current_key)
        if resolved_id is not None:
            emb_query = emb_query.join(
                CatalogSearchDocument,
                CatalogSearchDocument.id == CatalogEmbedding.search_document_id,
            ).where(CatalogSearchDocument.source_id == resolved_id)
        emb_by_doc = {
            e.search_document_id: e for e in session.scalars(emb_query).all()
        }
        stale = 0
        for doc in active_docs:
            emb = emb_by_doc.get(doc.id)
            if emb is None or emb.document_fingerprint != doc.document_fingerprint:
                stale += 1

        return EmbeddingStatsResponse(
            active_documents=active_documents,
            table_documents=table_documents,
            column_documents=column_documents,
            embedding_count=embedding_count,
            model_keys=sorted(model_keys),
            stale_documents=stale,
            embedding_provider=cfg.embedding_provider,
            embedding_device=cfg.embedding_device,
            embedding_dimension=cfg.embedding_dimension,
            source_id=resolved_id,
            source_name=resolved_name,
        )
    finally:
        session.close()


@router.get("/documents", response_model=list[SearchDocumentSummary])
def list_documents(
    object_type: str | None = None,
    active: bool | None = True,
    name: str | None = None,
    source_id: int | None = Query(default=None),
    source_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[SearchDocumentSummary]:
    session = _session()
    cfg = get_settings()
    try:
        resolved_id, _ = _resolve_source_filter(
            session, source_id=source_id, source_name=source_name
        )
        stmt = select(CatalogSearchDocument)
        if resolved_id is not None:
            stmt = stmt.where(CatalogSearchDocument.source_id == resolved_id)
        if object_type:
            stmt = stmt.where(CatalogSearchDocument.object_type == object_type.upper())
        if active is not None:
            stmt = stmt.where(CatalogSearchDocument.active.is_(active))
        if name:
            like = f"%{name.lower()}%"
            stmt = stmt.where(CatalogSearchDocument.document_key.ilike(like))
        stmt = stmt.order_by(CatalogSearchDocument.id).limit(limit)
        docs = session.scalars(stmt).all()

        provider = get_embedding_provider(cfg)
        current_key = provider.model_key
        emb_rows = session.scalars(
            select(CatalogEmbedding).where(
                CatalogEmbedding.search_document_id.in_([d.id for d in docs] or [-1]),
                CatalogEmbedding.model_key == current_key,
            )
        ).all()
        emb_by_doc = {e.search_document_id: e for e in emb_rows}

        result: list[SearchDocumentSummary] = []
        for d in docs:
            emb = emb_by_doc.get(d.id)
            result.append(
                SearchDocumentSummary(
                    id=d.id,
                    source_id=d.source_id,
                    object_type=d.object_type,
                    table_id=d.table_id,
                    column_id=d.column_id,
                    document_key=d.document_key,
                    document_fingerprint=d.document_fingerprint,
                    source_fingerprint=d.source_fingerprint,
                    builder_version=d.builder_version,
                    active=d.active,
                    has_embedding=emb is not None,
                    model_key=emb.model_key if emb else None,
                )
            )
        return result
    finally:
        session.close()


@router.get("/documents/{document_id}", response_model=SearchDocumentDetail)
def get_document(document_id: int) -> SearchDocumentDetail:
    session = _session()
    cfg = get_settings()
    try:
        doc = session.get(CatalogSearchDocument, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="search document not found")
        provider = get_embedding_provider(cfg)
        emb = session.scalar(
            select(CatalogEmbedding).where(
                CatalogEmbedding.search_document_id == doc.id,
                CatalogEmbedding.model_key == provider.model_key,
            )
        )
        return SearchDocumentDetail(
            id=doc.id,
            source_id=doc.source_id,
            object_type=doc.object_type,
            table_id=doc.table_id,
            column_id=doc.column_id,
            document_key=doc.document_key,
            searchable_text=doc.searchable_text,
            document_fingerprint=doc.document_fingerprint,
            source_fingerprint=doc.source_fingerprint,
            builder_version=doc.builder_version,
            active=doc.active,
            first_seen_at=doc.first_seen_at,
            last_seen_at=doc.last_seen_at,
            updated_at=doc.updated_at,
            has_embedding=emb is not None,
            model_key=emb.model_key if emb else None,
            embedding_dimension=emb.dimension if emb else None,
            model_name=emb.model_name if emb else None,
            model_revision=emb.model_revision if emb else None,
            normalized=emb.normalized if emb else None,
        )
    finally:
        session.close()
