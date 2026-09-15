"""Embedding pipeline service (incremental, CPU provider)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.bge_m3 import EmbeddingError
from app.embeddings.factory import get_embedding_provider
from app.models.catalog import (
    CatalogEmbedding,
    CatalogEmbeddingRun,
    CatalogSearchDocument,
    CatalogSource,
)
from app.services.search_document_builder import RebuildStats, SearchDocumentBuilder

logger = logging.getLogger(__name__)

_SENSITIVE_PATTERNS = [
    re.compile(r"postgresql\+?[^:\s]*://[^\s]+", re.IGNORECASE),
    re.compile(r"password[=:]\s*\S+", re.IGNORECASE),
]


def sanitize_error_message(message: str, settings: Settings | None = None) -> str:
    """Strip credentials / connection URLs from error text."""
    cfg = settings or get_settings()
    text = message or ""
    for secret in (
        cfg.medical_db_password,
        cfg.catalog_db_password,
        cfg.medical_db_url,
        cfg.catalog_db_url,
    ):
        if secret:
            text = text.replace(secret, "***")
    for pattern in _SENSITIVE_PATTERNS:
        text = pattern.sub("***", text)
    return text[:2000]


@dataclass
class EmbeddingRunResult:
    run_id: int
    status: str
    model_key: str
    documents: int
    embedded: int
    skipped: int
    failed: int
    started_at: datetime
    finished_at: datetime | None
    error_message: str | None = None
    error_code: str | None = None


class EmbeddingService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider or get_embedding_provider(self.settings)

    def rebuild_documents(self, source_name: str = "medical_demo") -> RebuildStats:
        builder = SearchDocumentBuilder(self.session)
        stats = builder.rebuild_for_source(source_name)
        self.session.commit()
        return stats

    def run_embedding(self, source_name: str = "medical_demo") -> EmbeddingRunResult:
        source = self.session.scalar(
            select(CatalogSource).where(CatalogSource.source_name == source_name)
        )
        if source is None:
            raise ValueError(f"catalog source not found: {source_name}")

        model_key = self.provider.model_key
        run = CatalogEmbeddingRun(
            source_id=source.id,
            status="RUNNING",
            model_key=model_key,
            started_at=datetime.now(timezone.utc),
        )
        self.session.add(run)
        self.session.commit()
        self.session.refresh(run)

        docs = list(
            self.session.scalars(
                select(CatalogSearchDocument)
                .where(
                    CatalogSearchDocument.source_id == source.id,
                    CatalogSearchDocument.active.is_(True),
                )
                .order_by(CatalogSearchDocument.id)
            ).all()
        )
        run.document_count = len(docs)
        self.session.commit()

        existing_by_doc = {
            e.search_document_id: e
            for e in self.session.scalars(
                select(CatalogEmbedding).where(CatalogEmbedding.model_key == model_key)
            ).all()
        }

        to_embed: list[CatalogSearchDocument] = []
        skipped = 0
        for doc in docs:
            current = existing_by_doc.get(doc.id)
            if (
                current is not None
                and current.document_fingerprint == doc.document_fingerprint
            ):
                skipped += 1
            else:
                to_embed.append(doc)

        embedded = 0
        failed = 0
        error_code: str | None = None
        error_message: str | None = None
        status = "SUCCESS"

        try:
            batch_size = max(1, self.settings.embedding_batch_size)
            for start in range(0, len(to_embed), batch_size):
                batch = to_embed[start : start + batch_size]
                texts = [d.searchable_text for d in batch]
                vectors = self.provider.embed_texts(texts)
                if len(vectors) != len(batch):
                    raise EmbeddingError(
                        "EMBEDDING_FAILED",
                        f"Provider returned {len(vectors)} vectors for {len(batch)} texts",
                    )
                now = datetime.now(timezone.utc)
                for doc, vec in zip(batch, vectors, strict=True):
                    if len(vec) != self.settings.embedding_dimension:
                        raise EmbeddingError(
                            "DIMENSION_MISMATCH",
                            f"Expected dimension {self.settings.embedding_dimension}, got {len(vec)}",
                        )
                    row = existing_by_doc.get(doc.id)
                    if row is None:
                        row = CatalogEmbedding(
                            search_document_id=doc.id,
                            model_key=model_key,
                            model_name=self.provider.model_name,
                            model_revision=self.provider.model_revision,
                            dimension=len(vec),
                            normalized=self.provider.normalized,
                            document_fingerprint=doc.document_fingerprint,
                            embedding=vec,
                            created_at=now,
                            updated_at=now,
                        )
                        self.session.add(row)
                        existing_by_doc[doc.id] = row
                    else:
                        row.model_name = self.provider.model_name
                        row.model_revision = self.provider.model_revision
                        row.dimension = len(vec)
                        row.normalized = self.provider.normalized
                        row.document_fingerprint = doc.document_fingerprint
                        row.embedding = vec
                        row.updated_at = now
                    embedded += 1
                self.session.commit()
        except EmbeddingError as exc:
            self.session.rollback()
            status = "FAILED"
            failed = max(len(to_embed) - embedded, 1)
            error_code = exc.code
            error_message = sanitize_error_message(str(exc), self.settings)
            logger.exception("Embedding run failed code=%s", error_code)
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            status = "FAILED"
            failed = max(len(to_embed) - embedded, 1)
            error_code = "EMBEDDING_FAILED"
            error_message = sanitize_error_message(type(exc).__name__, self.settings)
            logger.exception("Embedding run unexpected failure")

        run = self.session.get(CatalogEmbeddingRun, run.id)
        assert run is not None
        run.status = status
        run.embedded_count = embedded
        run.skipped_count = skipped
        run.failed_count = failed if status == "FAILED" else 0
        run.error_code = error_code
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        run.document_count = len(docs)
        run.model_key = model_key
        self.session.commit()
        self.session.refresh(run)

        return EmbeddingRunResult(
            run_id=run.id,
            status=run.status,
            model_key=run.model_key,
            documents=run.document_count,
            embedded=run.embedded_count,
            skipped=run.skipped_count,
            failed=run.failed_count,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error_message=run.error_message,
            error_code=run.error_code,
        )
