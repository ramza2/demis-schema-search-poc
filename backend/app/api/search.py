"""Schema search API (Step 4 / 4.1) — discovery only, no NL→SQL."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.db.session import get_catalog_session_factory
from app.schemas.search_api import (
    DirectResultOut,
    QueryInfo,
    RelatedTableOut,
    RelationHopOut,
    SchemaSearchRequest,
    SchemaSearchResponse,
)
from app.services.embedding_service import sanitize_error_message
from app.services.search.search_service import SchemaSearchService, SearchError

router = APIRouter(prefix="/api/v1/search", tags=["search"])


@router.post("/schema", response_model=SchemaSearchResponse)
def search_schema(body: SchemaSearchRequest) -> SchemaSearchResponse:
    settings = get_settings()
    session = get_catalog_session_factory()()
    try:
        service = SchemaSearchService(session, settings=settings)
        result = service.search(
            query=body.query,
            mode=body.mode,
            top_k=body.top_k,
            object_type=body.object_type,
            expand_terms=body.expand_terms,
            expand_relations_enabled=body.expand_relations,
            max_relation_hops=body.max_relation_hops,
            debug=body.debug,
            source_id=body.source_id,
            source_name=body.source_name,
        )
        return SchemaSearchResponse(
            query=QueryInfo(
                original=result.original_query,
                normalized=result.normalized_query,
                expanded=result.expanded_query,
                matched_concepts=result.matched_concepts,
                expanded_terms=result.expanded_terms,
            ),
            mode=result.mode,
            model_key=result.model_key,
            object_type=result.object_type,
            source_id=result.source_id,
            source_name=result.source_name,
            direct_results=[
                DirectResultOut(
                    rank=d.rank,
                    match_type=d.match_type,
                    object_type=d.object_type,
                    schema_name=d.schema_name,
                    table_name=d.table_name,
                    column_name=d.column_name,
                    document_key=d.document_key,
                    document_id=d.document_id,
                    semantic_score=d.semantic_score,
                    semantic_rank=d.semantic_rank,
                    keyword_score=d.keyword_score,
                    keyword_rank=d.keyword_rank,
                    rrf_score=d.rrf_score,
                    evidence=d.evidence,
                    searchable_snippet=d.searchable_snippet,
                )
                for d in result.direct_results
            ],
            related_tables=[
                RelatedTableOut(
                    table_name=r.table_name,
                    schema_name=r.schema_name,
                    seed_schema=r.seed_schema,
                    seed_table=r.seed_table,
                    hop_distance=r.hop_distance,
                    match_type=r.match_type,
                    relation_path=[
                        RelationHopOut(
                            from_schema=h.from_schema,
                            from_table=h.from_table,
                            to_schema=h.to_schema,
                            to_table=h.to_table,
                            constraint_name=h.constraint_name,
                            direction=h.direction,
                            from_columns=h.from_columns,
                            to_columns=h.to_columns,
                        )
                        for h in r.relation_path
                    ],
                )
                for r in result.related_tables
            ],
            elapsed_ms=result.elapsed_ms,
            timings=result.timings,
            debug=result.debug,
        )
    except SearchError as exc:
        status = 400
        if exc.code in {"EMBEDDING_NOT_FOUND", "SEMANTIC_PROVIDER_NOT_AVAILABLE"}:
            status = 409
        raise HTTPException(
            status_code=status,
            detail={
                "code": exc.code,
                "message": sanitize_error_message(str(exc), settings),
            },
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "code": "SEARCH_FAILED",
                "message": sanitize_error_message(f"{type(exc).__name__}", settings),
            },
        ) from exc
    finally:
        session.close()
