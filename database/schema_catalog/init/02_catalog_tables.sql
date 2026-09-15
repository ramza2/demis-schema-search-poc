-- ============================================================
-- schema_catalog tables for Step 2 (Schema Analyzer)
-- Idempotent CREATE IF NOT EXISTS for fresh volumes.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Keep Step 1 meta table, update step marker
UPDATE catalog_meta
SET meta_value = 'Step 2 - Schema Analyzer / Schema Catalog',
    updated_at = CURRENT_TIMESTAMP
WHERE meta_key = 'current_step';

UPDATE catalog_meta
SET meta_value = '0.2.0',
    updated_at = CURRENT_TIMESTAMP
WHERE meta_key = 'schema_version';

INSERT INTO catalog_meta (meta_key, meta_value)
VALUES ('current_step', 'Step 2 - Schema Analyzer / Schema Catalog')
ON CONFLICT (meta_key) DO UPDATE
SET meta_value = EXCLUDED.meta_value,
    updated_at = CURRENT_TIMESTAMP;

-- ------------------------------------------------------------
-- catalog_source
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_source (
    id                  BIGSERIAL PRIMARY KEY,
    source_name         VARCHAR(100) NOT NULL,
    db_type             VARCHAR(40)  NOT NULL,
    host                VARCHAR(255),
    port                INTEGER,
    database_name       VARCHAR(100) NOT NULL,
    default_schema      VARCHAR(100) NOT NULL DEFAULT 'public',
    username            VARCHAR(255),
    encrypted_password  TEXT,
    connection_options  JSONB,
    enabled             BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_catalog_source_name UNIQUE (source_name)
);

COMMENT ON TABLE catalog_source IS '분석 대상 DB Target Profile. DB Password는 Fernet 암호문으로만 저장한다.';
COMMENT ON COLUMN catalog_source.source_name IS 'Source 논리명';
COMMENT ON COLUMN catalog_source.db_type IS 'DBMS 종류(postgresql/mysql/mariadb/oracle)';
COMMENT ON COLUMN catalog_source.host IS 'Host (비민감 메타)';
COMMENT ON COLUMN catalog_source.port IS 'Port';
COMMENT ON COLUMN catalog_source.database_name IS 'Database 이름 (Oracle은 service/sid display용)';
COMMENT ON COLUMN catalog_source.default_schema IS '기본 분석 Schema / Owner';
COMMENT ON COLUMN catalog_source.username IS '접속 Username (Password 제외)';
COMMENT ON COLUMN catalog_source.encrypted_password IS 'Fernet ciphertext for Target DB password; plaintext is never stored';
COMMENT ON COLUMN catalog_source.connection_options IS '비민감 Connection Option JSON (service_name, sslmode 등)';

-- ------------------------------------------------------------
-- catalog_analysis_run
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_analysis_run (
    id                  BIGSERIAL PRIMARY KEY,
    source_id           BIGINT       NOT NULL REFERENCES catalog_source(id),
    status              VARCHAR(20)  NOT NULL,
    target_schema       VARCHAR(100) NOT NULL DEFAULT 'public',
    started_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    table_count         INTEGER      NOT NULL DEFAULT 0,
    column_count        INTEGER      NOT NULL DEFAULT 0,
    relation_count      INTEGER      NOT NULL DEFAULT 0,
    index_count         INTEGER      NOT NULL DEFAULT 0,
    schema_fingerprint  VARCHAR(64),
    error_message       TEXT,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_analysis_run_status CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS ix_analysis_run_source ON catalog_analysis_run (source_id, started_at DESC);

COMMENT ON TABLE catalog_analysis_run IS 'Schema 분석 실행 이력';

-- ------------------------------------------------------------
-- catalog_table
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_table (
    id                  BIGSERIAL PRIMARY KEY,
    source_id           BIGINT       NOT NULL REFERENCES catalog_source(id),
    schema_name         VARCHAR(100) NOT NULL,
    table_name          VARCHAR(200) NOT NULL,
    table_type          VARCHAR(50)  NOT NULL DEFAULT 'BASE TABLE',
    table_comment       TEXT,
    object_fingerprint  VARCHAR(64)  NOT NULL,
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id         BIGINT       REFERENCES catalog_analysis_run(id),
    active              BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_catalog_table UNIQUE (source_id, schema_name, table_name)
);

CREATE INDEX IF NOT EXISTS ix_catalog_table_active ON catalog_table (source_id, active);
CREATE INDEX IF NOT EXISTS ix_catalog_table_name ON catalog_table (table_name);

COMMENT ON TABLE catalog_table IS '분석된 Table 메타데이터';

-- ------------------------------------------------------------
-- catalog_column
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_column (
    id                         BIGSERIAL PRIMARY KEY,
    table_id                   BIGINT       NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    ordinal_position           INTEGER      NOT NULL,
    column_name                VARCHAR(200) NOT NULL,
    data_type                  VARCHAR(100) NOT NULL,
    character_maximum_length   INTEGER,
    numeric_precision          INTEGER,
    numeric_scale              INTEGER,
    is_nullable                BOOLEAN      NOT NULL DEFAULT TRUE,
    default_value              TEXT,
    column_comment             TEXT,
    is_primary_key             BOOLEAN      NOT NULL DEFAULT FALSE,
    is_unique                  BOOLEAN      NOT NULL DEFAULT FALSE,
    object_fingerprint         VARCHAR(64)  NOT NULL,
    first_seen_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id                BIGINT       REFERENCES catalog_analysis_run(id),
    active                     BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_catalog_column UNIQUE (table_id, column_name)
);

CREATE INDEX IF NOT EXISTS ix_catalog_column_table ON catalog_column (table_id, ordinal_position);

COMMENT ON TABLE catalog_column IS '분석된 Column 메타데이터';
COMMENT ON COLUMN catalog_column.is_primary_key IS 'PK 구성 컬럼 여부(복합 PK 포함)';
COMMENT ON COLUMN catalog_column.is_unique IS '해당 컬럼 단독 UNIQUE 여부. 복합 PK/UNIQUE 구성 컬럼은 false';

-- ------------------------------------------------------------
-- catalog_key_constraint / catalog_key_constraint_column
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_key_constraint (
    id                  BIGSERIAL PRIMARY KEY,
    table_id            BIGINT       NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    constraint_name     VARCHAR(200) NOT NULL,
    constraint_type     VARCHAR(20)  NOT NULL,
    object_fingerprint  VARCHAR(64)  NOT NULL,
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id         BIGINT       REFERENCES catalog_analysis_run(id),
    active              BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_catalog_key_constraint UNIQUE (table_id, constraint_name),
    CONSTRAINT ck_catalog_key_constraint_type
        CHECK (constraint_type IN ('PRIMARY_KEY', 'UNIQUE'))
);

CREATE TABLE IF NOT EXISTS catalog_key_constraint_column (
    id                  BIGSERIAL PRIMARY KEY,
    constraint_id       BIGINT  NOT NULL REFERENCES catalog_key_constraint(id) ON DELETE CASCADE,
    ordinal_position    INTEGER NOT NULL,
    column_id           BIGINT  NOT NULL REFERENCES catalog_column(id) ON DELETE CASCADE,
    CONSTRAINT uq_catalog_key_constraint_column UNIQUE (constraint_id, ordinal_position)
);

COMMENT ON TABLE catalog_key_constraint IS 'PRIMARY KEY / UNIQUE Constraint (복합키 순서 보존)';
COMMENT ON TABLE catalog_key_constraint_column IS 'Key Constraint Column ordinal mapping';

-- ------------------------------------------------------------
-- catalog_relation / catalog_relation_column
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_relation (
    id                  BIGSERIAL PRIMARY KEY,
    source_id           BIGINT       NOT NULL REFERENCES catalog_source(id),
    constraint_name     VARCHAR(200) NOT NULL,
    source_table_id     BIGINT       NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    target_table_id     BIGINT       NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    relation_type       VARCHAR(40)  NOT NULL DEFAULT 'FOREIGN_KEY',
    object_fingerprint  VARCHAR(64)  NOT NULL,
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id         BIGINT       REFERENCES catalog_analysis_run(id),
    active              BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Natural key: (source_table_id, constraint_name) — same FK name on different tables is allowed
    CONSTRAINT uq_catalog_relation UNIQUE (source_table_id, constraint_name)
);

CREATE INDEX IF NOT EXISTS ix_catalog_relation_src ON catalog_relation (source_table_id);
CREATE INDEX IF NOT EXISTS ix_catalog_relation_tgt ON catalog_relation (target_table_id);

CREATE TABLE IF NOT EXISTS catalog_relation_column (
    id                  BIGSERIAL PRIMARY KEY,
    relation_id         BIGINT  NOT NULL REFERENCES catalog_relation(id) ON DELETE CASCADE,
    ordinal_position    INTEGER NOT NULL,
    source_column_id    BIGINT  NOT NULL REFERENCES catalog_column(id) ON DELETE CASCADE,
    target_column_id    BIGINT  NOT NULL REFERENCES catalog_column(id) ON DELETE CASCADE,
    CONSTRAINT uq_catalog_relation_column UNIQUE (relation_id, ordinal_position)
);

COMMENT ON TABLE catalog_relation IS 'FK Relationship 메타데이터';
COMMENT ON TABLE catalog_relation_column IS 'Composite FK Column Mapping';

-- ------------------------------------------------------------
-- catalog_index / catalog_index_column
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalog_index (
    id                  BIGSERIAL PRIMARY KEY,
    table_id            BIGINT       NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    index_name          VARCHAR(200) NOT NULL,
    is_unique           BOOLEAN      NOT NULL DEFAULT FALSE,
    index_method        VARCHAR(50),
    index_definition    TEXT,
    object_fingerprint  VARCHAR(64)  NOT NULL,
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_run_id         BIGINT       REFERENCES catalog_analysis_run(id),
    active              BOOLEAN      NOT NULL DEFAULT TRUE,
    CONSTRAINT uq_catalog_index UNIQUE (table_id, index_name)
);

CREATE TABLE IF NOT EXISTS catalog_index_column (
    id                  BIGSERIAL PRIMARY KEY,
    index_id            BIGINT       NOT NULL REFERENCES catalog_index(id) ON DELETE CASCADE,
    ordinal_position    INTEGER      NOT NULL,
    column_name         VARCHAR(200) NOT NULL,
    CONSTRAINT uq_catalog_index_column UNIQUE (index_id, ordinal_position)
);

COMMENT ON TABLE catalog_index IS 'Index 메타데이터';
COMMENT ON TABLE catalog_index_column IS 'Index Column 순서';

-- Default medical_demo source (no password stored)
INSERT INTO catalog_source (
    source_name, db_type, host, port, database_name, default_schema, username, enabled
) VALUES (
    'medical_demo', 'postgresql', 'medical-db', 5432, 'medical_demo', 'public', 'medical_user', TRUE
)
ON CONFLICT (source_name) DO UPDATE
SET db_type = EXCLUDED.db_type,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    database_name = EXCLUDED.database_name,
    default_schema = EXCLUDED.default_schema,
    username = EXCLUDED.username,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();
