"""Backend / DB integration tests for Step 1."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

REQUIRED_TABLES = [
    "tb_pt_mst",
    "tb_enc_hist",
    "tb_dgn_hist",
    "tb_dgn_cd_mst",
    "tb_ord_hdr",
    "tb_ord_dtl",
    "tb_lab_ord",
    "tb_lab_rst",
    "tb_lab_mst",
    "tb_lab_ref",
    "tb_med_ord",
    "tb_drug_mst",
    "tb_img_ord",
    "tb_img_rpt",
    "tb_img_mst",
    "tb_cln_doc",
    "tb_doc_type",
    "tb_dept_mst",
    "tb_provider",
    "tb_proc_hist",
    "tb_proc_mst",
    "tb_code_mst",
    "tb_ward_mst",
    "tb_adm_hist",
]

CORE_FK_PAIRS = [
    ("tb_enc_hist", "fk_enc_pt"),
    ("tb_lab_ord", "fk_lab_ord_enc"),
    ("tb_lab_rst", "fk_lab_rst_ord"),
    ("tb_lab_rst", "fk_lab_rst_exm"),
    ("tb_med_ord", "fk_med_ord_drug"),
    ("tb_img_rpt", "fk_img_rpt_ord"),
    ("tb_cln_doc", "fk_cln_doc_typ"),
]


def _medical_url() -> str:
    host = os.getenv("MEDICAL_DB_HOST", "localhost")
    port = os.getenv("MEDICAL_DB_PORT", "5433")
    name = os.getenv("MEDICAL_DB_NAME", "medical_demo")
    user = os.getenv("MEDICAL_DB_USER", "medical_user")
    password = os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


def _catalog_url() -> str:
    host = os.getenv("CATALOG_DB_HOST", "localhost")
    port = os.getenv("CATALOG_DB_PORT", "5434")
    name = os.getenv("CATALOG_DB_NAME", "schema_catalog")
    user = os.getenv("CATALOG_DB_USER", "catalog_user")
    password = os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"


@pytest.fixture(scope="session")
def medical_engine():
    engine = create_engine(_medical_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


@pytest.fixture(scope="session")
def catalog_engine():
    engine = create_engine(_catalog_url(), pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


def test_backend_health_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Point app settings at compose-exposed ports for local pytest.
    monkeypatch.setenv("MEDICAL_DB_HOST", os.getenv("MEDICAL_DB_HOST", "localhost"))
    monkeypatch.setenv("MEDICAL_DB_PORT", os.getenv("MEDICAL_DB_PORT", "5433"))
    monkeypatch.setenv("CATALOG_DB_HOST", os.getenv("CATALOG_DB_HOST", "localhost"))
    monkeypatch.setenv("CATALOG_DB_PORT", os.getenv("CATALOG_DB_PORT", "5434"))
    monkeypatch.setenv("MEDICAL_DB_PASSWORD", os.getenv("MEDICAL_DB_PASSWORD", "medical_pass_change_me"))
    monkeypatch.setenv("CATALOG_DB_PASSWORD", os.getenv("CATALOG_DB_PASSWORD", "catalog_pass_change_me"))

    from app.core.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["backend"] == "ok"
    assert payload["status"] in {"ok", "degraded"}
    assert "medical_db" in payload
    assert "catalog_db" in payload


def test_medical_db_connection(medical_engine) -> None:
    with medical_engine.connect() as conn:
        result = conn.execute(text("SELECT current_database()")).scalar_one()
    assert result == "medical_demo"


def test_catalog_db_connection(catalog_engine) -> None:
    with catalog_engine.connect() as conn:
        result = conn.execute(text("SELECT current_database()")).scalar_one()
        meta = conn.execute(text("SELECT COUNT(*) FROM catalog_meta")).scalar_one()
    assert result == "schema_catalog"
    assert meta >= 1


def test_required_tables_exist(medical_engine) -> None:
    with medical_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                """
            )
        ).fetchall()
    names = {r[0] for r in rows}
    missing = [t for t in REQUIRED_TABLES if t not in names]
    assert not missing, f"Missing tables: {missing}"
    assert len(names) >= 20


def test_pk_fk_constraints(medical_engine) -> None:
    with medical_engine.connect() as conn:
        pk_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.table_constraints
                WHERE table_schema = 'public' AND constraint_type = 'PRIMARY KEY'
                """
            )
        ).scalar_one()
        fk_count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.table_constraints
                WHERE table_schema = 'public' AND constraint_type = 'FOREIGN KEY'
                """
            )
        ).scalar_one()
        existing = {
            (r[0], r[1])
            for r in conn.execute(
                text(
                    """
                    SELECT table_name, constraint_name
                    FROM information_schema.table_constraints
                    WHERE table_schema = 'public' AND constraint_type = 'FOREIGN KEY'
                    """
                )
            ).fetchall()
        }
    assert pk_count >= 20
    assert fk_count >= 20
    missing = [pair for pair in CORE_FK_PAIRS if pair not in existing]
    assert not missing, f"Missing FK constraints: {missing}"


def test_seed_data_present(medical_engine) -> None:
    queries = {
        "patients": "SELECT COUNT(*) FROM TB_PT_MST",
        "encounters": "SELECT COUNT(*) FROM TB_ENC_HIST",
        "diagnoses": "SELECT COUNT(*) FROM TB_DGN_HIST",
        "lab_results": "SELECT COUNT(*) FROM TB_LAB_RST",
        "medications": "SELECT COUNT(*) FROM TB_MED_ORD",
        "imaging_reports": "SELECT COUNT(*) FROM TB_IMG_RPT",
        "clinical_documents": "SELECT COUNT(*) FROM TB_CLN_DOC",
    }
    with medical_engine.connect() as conn:
        counts = {k: conn.execute(text(q)).scalar_one() for k, q in queries.items()}
    assert counts["patients"] >= 100
    assert counts["encounters"] >= counts["patients"]
    assert counts["diagnoses"] > 0
    assert counts["lab_results"] > 0
    assert counts["medications"] > 0
    assert counts["imaging_reports"] > 0
    assert counts["clinical_documents"] > 0


def test_core_relationship_joins(medical_engine) -> None:
    sql = text(
        """
        SELECT COUNT(*)
        FROM TB_PT_MST p
        JOIN TB_ENC_HIST e ON e.PT_NO = p.PT_NO
        JOIN TB_LAB_ORD lo ON lo.ENC_ID = e.ENC_ID
        JOIN TB_LAB_RST lr ON lr.LAB_ORD_ID = lo.LAB_ORD_ID
        JOIN TB_LAB_MST lm ON lm.EXM_CD = lr.EXM_CD
        WHERE lm.EXM_CAT IN ('LIVER', 'GLUCOSE', 'KIDNEY')
        """
    )
    with medical_engine.connect() as conn:
        joined = conn.execute(sql).scalar_one()
    assert joined > 0


EXPECTED_INDEXES = [
    "ix_pt_nm",
    "ix_pt_brth",
    "ix_enc_pt",
    "ix_enc_dt",
    "ix_enc_dept",
    "ix_enc_typ",
    "ix_adm_pt",
    "ix_adm_ward",
    "ix_dgn_enc",
    "ix_dgn_pt",
    "ix_dgn_cd",
    "ix_dgn_dt",
    "ix_proc_enc",
    "ix_proc_pt",
    "ix_ord_enc",
    "ix_ord_pt",
    "ix_ord_typ",
    "ix_ord_dt",
    "ix_ord_dtl_no",
    "ix_lab_ord_enc",
    "ix_lab_ord_pt",
    "ix_lab_ord_exm",
    "ix_lab_rst_pt",
    "ix_lab_rst_exm",
    "ix_lab_rst_dt",
    "ix_med_ord_pt",
    "ix_med_ord_drug",
    "ix_med_ord_enc",
    "ix_img_ord_pt",
    "ix_img_ord_enc",
    "ix_img_ord_cd",
    "ix_img_rpt_pt",
    "ix_img_rpt_dt",
    "ix_cln_doc_enc",
    "ix_cln_doc_pt",
    "ix_cln_doc_typ",
    "ix_lab_mst_cat",
    "ix_lab_ref_exm",
    "ix_prov_dept",
    "ix_code_grp",
]

# Business-critical columns that Schema Analyzer should always see with comments.
REQUIRED_COLUMN_COMMENTS = [
    ("tb_pt_mst", "pt_no"),
    ("tb_pt_mst", "pt_nm"),
    ("tb_pt_mst", "brth_dt"),
    ("tb_pt_mst", "sex_cd"),
    ("tb_enc_hist", "enc_id"),
    ("tb_enc_hist", "pt_no"),
    ("tb_enc_hist", "enc_typ"),
    ("tb_enc_hist", "adm_dt"),
    ("tb_dgn_hist", "dgn_cd"),
    ("tb_dgn_hist", "dgn_dt"),
    ("tb_dgn_hist", "dgn_typ"),
    ("tb_ord_hdr", "ord_no"),
    ("tb_ord_hdr", "ord_typ"),
    ("tb_ord_hdr", "ord_dt"),
    ("tb_lab_ord", "exm_cd"),
    ("tb_lab_rst", "exm_cd"),
    ("tb_lab_rst", "rst_val"),
    ("tb_lab_rst", "rst_num"),
    ("tb_lab_rst", "rst_dt"),
    ("tb_lab_mst", "exm_cd"),
    ("tb_lab_mst", "exm_nm"),
    ("tb_lab_mst", "exm_cat"),
    ("tb_med_ord", "drug_cd"),
    ("tb_drug_mst", "drug_cd"),
    ("tb_drug_mst", "drug_nm"),
    ("tb_img_ord", "img_cd"),
    ("tb_img_rpt", "find_txt"),
    ("tb_img_rpt", "impr_txt"),
    ("tb_cln_doc", "doc_typ_cd"),
    ("tb_cln_doc", "doc_ttl"),
    ("tb_doc_type", "doc_typ_nm"),
]

# Evaluation-query leakage phrases must not appear in schema comments.
FORBIDDEN_COMMENT_PHRASES = [
    "검색의 핵심",
    "검색에 사용",
    "검색에 활용",
    "검색 핵심",
    "검색의 기준",
    "핵심 기준 테이블",
    "진단 이력 검색",
    "간수치·혈당·신장기능 검색",
]


def test_table_and_column_comments_exist(medical_engine) -> None:
    with medical_engine.connect() as conn:
        table_comments = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_catalog.pg_description d
                JOIN pg_catalog.pg_class c ON c.oid = d.objoid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r' AND d.objsubid = 0
                """
            )
        ).scalar_one()
        column_comments = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_catalog.pg_description d
                JOIN pg_catalog.pg_class c ON c.oid = d.objoid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'r' AND d.objsubid > 0
                """
            )
        ).scalar_one()
    assert table_comments >= 20
    assert column_comments >= 50


def test_all_required_tables_have_comments(medical_engine) -> None:
    with medical_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       COALESCE(d.description, '') AS table_comment
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_catalog.pg_description d
                  ON d.objoid = c.oid AND d.objsubid = 0
                WHERE n.nspname = 'public' AND c.relkind = 'r'
                """
            )
        ).fetchall()
    comments = {r[0]: (r[1] or "").strip() for r in rows}
    missing = [t for t in REQUIRED_TABLES if not comments.get(t)]
    assert not missing, f"Tables missing COMMENT: {missing}"


def test_required_business_columns_have_comments(medical_engine) -> None:
    with medical_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname AS table_name,
                       a.attname AS column_name,
                       COALESCE(d.description, '') AS column_comment
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
                LEFT JOIN pg_catalog.pg_description d
                  ON d.objoid = c.oid AND d.objsubid = a.attnum
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            )
        ).fetchall()
    commented = {(r[0], r[1]): (r[2] or "").strip() for r in rows}
    missing = [f"{t}.{c}" for t, c in REQUIRED_COLUMN_COMMENTS if not commented.get((t, c))]
    assert not missing, f"Business columns missing COMMENT: {missing}"


def test_expected_indexes_exist(medical_engine) -> None:
    with medical_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'public'
                """
            )
        ).fetchall()
    existing = {r[0] for r in rows}
    missing = [idx for idx in EXPECTED_INDEXES if idx not in existing]
    assert not missing, f"Missing indexes: {missing}"


def test_column_comment_coverage(medical_engine) -> None:
    """Schema Analyzer relies on comments; require high coverage on business columns."""
    with medical_engine.connect() as conn:
        total_cols = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.columns
                WHERE table_schema = 'public'
                """
            )
        ).scalar_one()
        commented_cols = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM pg_catalog.pg_description d
                JOIN pg_catalog.pg_class c ON c.oid = d.objoid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND d.objsubid > 0
                  AND COALESCE(d.description, '') <> ''
                """
            )
        ).scalar_one()
    assert total_cols > 0
    coverage = commented_cols / total_cols
    # Mock DB is fully documented; keep threshold high for analyzer input quality.
    assert coverage >= 0.90, (
        f"Column COMMENT coverage too low: {coverage:.1%} "
        f"({commented_cols}/{total_cols}); expected >= 90%"
    )


def test_comments_have_no_evaluation_leakage(medical_engine) -> None:
    with medical_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.relname AS object_name,
                       CASE WHEN d.objsubid = 0 THEN NULL ELSE a.attname END AS column_name,
                       d.description
                FROM pg_catalog.pg_description d
                JOIN pg_catalog.pg_class c ON c.oid = d.objoid
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                LEFT JOIN pg_catalog.pg_attribute a
                  ON a.attrelid = c.oid AND a.attnum = d.objsubid
                WHERE n.nspname = 'public'
                  AND c.relkind = 'r'
                  AND COALESCE(d.description, '') <> ''
                """
            )
        ).fetchall()
    leaks: list[str] = []
    for object_name, column_name, description in rows:
        text_value = description or ""
        for phrase in FORBIDDEN_COMMENT_PHRASES:
            if phrase in text_value:
                target = object_name if column_name is None else f"{object_name}.{column_name}"
                leaks.append(f"{target}: contains '{phrase}'")
    assert not leaks, "Evaluation-leakage phrases found in COMMENTs:\n" + "\n".join(leaks)
