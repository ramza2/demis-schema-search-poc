-- ============================================================
-- schema_catalog bootstrap (Step 1)
-- Detailed catalog models / embedding tables arrive in Step 2+.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Placeholder for future pgvector (safe if image supports it)
-- CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS catalog_meta (
    meta_key     VARCHAR(100) PRIMARY KEY,
    meta_value   TEXT         NOT NULL,
    updated_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE catalog_meta IS '스키마 카탈로그 시스템 메타정보. Step 1에서는 연결/초기화 검증용으로만 사용한다.';
COMMENT ON COLUMN catalog_meta.meta_key IS '메타키';
COMMENT ON COLUMN catalog_meta.meta_value IS '메타값';
COMMENT ON COLUMN catalog_meta.updated_at IS '갱신일시';

INSERT INTO catalog_meta (meta_key, meta_value)
VALUES
    ('poc_name', 'DEMIS Schema Semantic Search PoC'),
    ('current_step', 'Step 2 - Schema Analyzer / Schema Catalog'),
    ('schema_version', '0.2.0')
ON CONFLICT (meta_key) DO UPDATE
SET meta_value = EXCLUDED.meta_value,
    updated_at = CURRENT_TIMESTAMP;
