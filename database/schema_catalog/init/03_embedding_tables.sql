-- ============================================================
-- schema_catalog tables for Step 3 (Search Document + Embedding)
-- Derived data only — does not mutate raw Step 2 catalog tables.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS vector;

UPDATE catalog_meta
SET meta_value = 'Step 3 - CPU-only Embedding Pipeline + pgvector',
    updated_at = CURRENT_TIMESTAMP
WHERE meta_key = 'current_step';

UPDATE catalog_meta
SET meta_value = '0.3.0',
    updated_at = CURRENT_TIMESTAMP
WHERE meta_key = 'schema_version';

INSERT INTO catalog_meta (meta_key, meta_value)
VALUES ('current_step', 'Step 3 - CPU-only Embedding Pipeline + pgvector')
ON CONFLICT (meta_key) DO UPDATE
SET meta_value = EXCLUDED.meta_value,
    updated_at = CURRENT_TIMESTAMP;

-- ------------------------------------------------------------
-- catalog_search_document (derived searchable text)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_search_document (
    id                   BIGSERIAL PRIMARY KEY,
    source_id            BIGINT       NOT NULL REFERENCES catalog_source(id),
    object_type          VARCHAR(20)  NOT NULL,
    table_id             BIGINT       REFERENCES catalog_table(id) ON DELETE SET NULL,
    column_id            BIGINT       REFERENCES catalog_column(id) ON DELETE SET NULL,
    document_key         VARCHAR(512) NOT NULL,
    searchable_text      TEXT         NOT NULL,
    source_fingerprint   VARCHAR(64)  NOT NULL,
    document_fingerprint VARCHAR(64)  NOT NULL,
    builder_version      VARCHAR(40)  NOT NULL,
    active               BOOLEAN      NOT NULL DEFAULT TRUE,
    first_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id          BIGINT,
    CONSTRAINT uq_catalog_search_document_key UNIQUE (document_key),
    CONSTRAINT ck_catalog_search_document_object_type
        CHECK (object_type IN ('TABLE', 'COLUMN'))
);

CREATE INDEX IF NOT EXISTS ix_catalog_search_document_source
    ON catalog_search_document (source_id);
CREATE INDEX IF NOT EXISTS ix_catalog_search_document_object_type
    ON catalog_search_document (object_type);
CREATE INDEX IF NOT EXISTS ix_catalog_search_document_active
    ON catalog_search_document (active);

COMMENT ON TABLE catalog_search_document IS
    'Raw Catalog에서 Rule 기반으로 생성한 검색용 Document. 언제든 재생성 가능한 Derived Data.';
COMMENT ON COLUMN catalog_search_document.document_key IS
    '안정적인 Natural Key (table:... / column:...)';
COMMENT ON COLUMN catalog_search_document.searchable_text IS
    'Embedding 입력용 deterministic 텍스트. Schema Metadata만 포함.';
COMMENT ON COLUMN catalog_search_document.source_fingerprint IS
    '생성에 사용된 Raw Catalog 상태 fingerprint';
COMMENT ON COLUMN catalog_search_document.document_fingerprint IS
    'object identity + searchable_text + builder_version 기반 SHA-256';

-- ------------------------------------------------------------
-- catalog_embedding_run
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_embedding_run (
    id              BIGSERIAL PRIMARY KEY,
    source_id       BIGINT       NOT NULL REFERENCES catalog_source(id),
    status          VARCHAR(20)  NOT NULL,
    model_key       VARCHAR(512) NOT NULL,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    document_count  INTEGER      NOT NULL DEFAULT 0,
    embedded_count  INTEGER      NOT NULL DEFAULT 0,
    skipped_count   INTEGER      NOT NULL DEFAULT 0,
    failed_count    INTEGER      NOT NULL DEFAULT 0,
    error_message   TEXT,
    error_code      VARCHAR(80),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_catalog_embedding_run_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS ix_catalog_embedding_run_source
    ON catalog_embedding_run (source_id);

COMMENT ON TABLE catalog_embedding_run IS
    'Embedding 실행 이력. Schema Analysis Run과는 별개.';

-- ------------------------------------------------------------
-- catalog_embedding (VECTOR 1024)
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_embedding (
    id                   BIGSERIAL PRIMARY KEY,
    search_document_id   BIGINT       NOT NULL REFERENCES catalog_search_document(id) ON DELETE CASCADE,
    model_key            VARCHAR(512) NOT NULL,
    model_name           VARCHAR(255) NOT NULL,
    model_revision       VARCHAR(120),
    dimension            INTEGER      NOT NULL,
    normalized           BOOLEAN      NOT NULL DEFAULT TRUE,
    document_fingerprint VARCHAR(64)  NOT NULL,
    embedding            VECTOR(1024) NOT NULL,
    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_catalog_embedding_doc_model UNIQUE (search_document_id, model_key)
);

CREATE INDEX IF NOT EXISTS ix_catalog_embedding_model_key
    ON catalog_embedding (model_key);

COMMENT ON TABLE catalog_embedding IS
    'Search Document의 Embedding Vector. (search_document_id, model_key) Natural Key.';
COMMENT ON COLUMN catalog_embedding.embedding IS 'BGE-M3 등 Embedding VECTOR(1024)';
COMMENT ON COLUMN catalog_embedding.model_key IS
    'model identity + dim + normalize + maxlen 조합 식별자';
