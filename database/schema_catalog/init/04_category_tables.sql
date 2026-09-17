CREATE TABLE IF NOT EXISTS catalog_category (
    id BIGSERIAL PRIMARY KEY,
    source_id BIGINT NOT NULL REFERENCES catalog_source(id) ON DELETE CASCADE,
    category_key VARCHAR(100) NOT NULL,
    category_name VARCHAR(200) NOT NULL,
    description TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_catalog_category_source_key UNIQUE (source_id, category_key)
);

CREATE TABLE IF NOT EXISTS catalog_table_category (
    id BIGSERIAL PRIMARY KEY,
    table_id BIGINT NOT NULL REFERENCES catalog_table(id) ON DELETE CASCADE,
    category_id BIGINT NOT NULL REFERENCES catalog_category(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    assignment_source VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    confidence DOUBLE PRECISION,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_catalog_table_category UNIQUE (table_id, category_id),
    CONSTRAINT ck_catalog_table_category_confidence
        CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    CONSTRAINT ck_catalog_table_category_assignment_source
        CHECK (assignment_source IN ('MANUAL', 'AUTO', 'IMPORT'))
);

CREATE INDEX IF NOT EXISTS ix_catalog_category_source
    ON catalog_category (source_id, active, sort_order);

CREATE INDEX IF NOT EXISTS ix_catalog_table_category_table
    ON catalog_table_category (table_id);

CREATE INDEX IF NOT EXISTS ix_catalog_table_category_category
    ON catalog_table_category (category_id);
