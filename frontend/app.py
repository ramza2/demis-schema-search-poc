"""Streamlit UI — DEMIS Schema Analyzer."""

from __future__ import annotations

import csv
import json
import os
from typing import Any

import requests
import streamlit as st

from helpers import LOAD_TARGETS_TIMEOUT_SECONDS
from target_dashboard import render_target_dashboard

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def api_get(path: str, **kwargs: Any) -> requests.Response:
    return requests.get(f"{BACKEND_URL}{path}", timeout=kwargs.pop("timeout", 30), **kwargs)


def api_post(path: str, **kwargs: Any) -> requests.Response:
    return requests.post(f"{BACKEND_URL}{path}", timeout=kwargs.pop("timeout", 120), **kwargs)


def api_put(path: str, **kwargs: Any) -> requests.Response:
    return requests.put(f"{BACKEND_URL}{path}", timeout=kwargs.pop("timeout", 120), **kwargs)


def api_delete(path: str, **kwargs: Any) -> requests.Response:
    return requests.delete(f"{BACKEND_URL}{path}", timeout=kwargs.pop("timeout", 120), **kwargs)


def load_targets() -> tuple[list[dict[str, Any]], str | None]:
    """Load targets without stopping the page. Returns (targets, error_message)."""
    try:
        resp = api_get("/api/v1/targets", timeout=LOAD_TARGETS_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return [], "Unexpected targets payload"
        return data, None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


def target_label(t: dict[str, Any]) -> str:
    return f"{t.get('source_name')} / {t.get('db_type')} / {t.get('host')}"


def target_selector(
    targets: list[dict[str, Any]],
    *,
    key: str,
    required: bool = False,
) -> dict[str, Any] | None:
    if not targets:
        st.info("등록된 Target이 없습니다. DB Targets 탭에서 추가하세요.")
        return None
    labels = [target_label(t) for t in targets]
    options = labels if required else ["— 선택 —"] + labels
    choice = st.selectbox("Target", options, key=key)
    if choice == "— 선택 —":
        return None
    idx = labels.index(choice)
    return targets[idx]


def show_response(resp: requests.Response) -> None:
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text}
    if resp.ok:
        st.success(f"HTTP {resp.status_code}")
        st.json(body)
    else:
        st.error(f"HTTP {resp.status_code}")
        st.json(body if isinstance(body, dict) else {"error": body})


def _status_mark(value: Any) -> str:
    normalized = str(value or "unknown").strip().lower()
    return "●" if normalized in {"ok", "healthy", "ready", "up", "available"} else "○"


# ---------------------------------------------------------------------------
# Page setup + shared header
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DEMIS Schema Analyzer",
    page_icon="🏥",
    layout="wide",
)

st.title("DEMIS Schema Analyzer")
st.caption("Multi-DB Schema Analysis & Catalog Explorer")
st.write(
    "DB Schema를 분석하여 Table·Column·관계정보를 Catalog화하고, "
    "검색과 명세 탐색을 지원합니다."
)

try:
    health_resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    health_resp.raise_for_status()
    health = health_resp.json()
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.stop()

provider = "unknown"
stats: dict[str, Any] = {}
try:
    stats_resp = api_get("/api/v1/embeddings/stats", timeout=10)
    if stats_resp.ok:
        stats = stats_resp.json()
        provider = stats.get("embedding_provider") or stats.get("provider") or "unknown"
except Exception:  # noqa: BLE001
    pass

st.caption(
    f"Backend {_status_mark(health.get('backend'))} {health.get('backend', 'unknown')} · "
    f"Catalog {_status_mark(health.get('catalog_db'))} {health.get('catalog_db', 'unknown')} · "
    f"Embedding ● {provider}"
)

with st.expander("시스템 상태 상세", expanded=False):
    c1, c2, c3 = st.columns(3)
    c1.metric("Backend", health.get("backend", "unknown"))
    c2.metric("medical_demo", health.get("medical_db", "unknown"))
    c3.metric("schema_catalog", health.get("catalog_db", "unknown"))
    st.caption(f"Backend URL: {BACKEND_URL}")
    st.caption(f"step={health.get('step', '')} · status={health.get('status', '')}")
    if health.get("medical_db_required") is False:
        st.caption("medical_demo는 optional이며 catalog/backend만 health 필수입니다.")
    if stats:
        st.write(
            {
                "embedding_provider": provider,
                "device": stats.get("embedding_device"),
                "dimension": stats.get("embedding_dimension"),
                "active_documents": stats.get("active_documents"),
                "embedding_count": stats.get("embedding_count"),
            }
        )
        if str(provider).lower() == "fake":
            st.warning(
                "Fake Embedding은 테스트 전용입니다. Semantic/Hybrid 검색은 "
                "ALLOW_FAKE_SEMANTIC_SEARCH=true일 때만 허용됩니다."
            )

st.divider()

# Create tabs before Target API calls so navigation stays available on timeouts.
tab_targets, tab_explorer, tab_search, tab_eval = st.tabs(
    ["DB Targets", "Catalog Explorer", "Schema Search", "검증 결과"]
)
targets, targets_load_error = load_targets()


# ---------------------------------------------------------------------------
# Tab 1: DB Targets
# ---------------------------------------------------------------------------

with tab_targets:
    render_target_dashboard(
        targets=targets,
        targets_load_error=targets_load_error,
        api_post=api_post,
        api_put=api_put,
        api_delete=api_delete,
        show_response=show_response,
    )


# ---------------------------------------------------------------------------
# Tab 2: Catalog Explorer
# ---------------------------------------------------------------------------

with tab_explorer:
    st.markdown("### Catalog Explorer")
    explorer_target = target_selector(targets, key="explorer_target", required=True)
    if explorer_target:
        tid = explorer_target["id"]
        try:
            emb_stats = api_get(
                "/api/v1/embeddings/stats",
                params={"source_id": tid},
                timeout=10,
            ).json()
            st.markdown("#### Embedding / Documents (선택된 Target)")
            e1, e2, e3, e4, e5 = st.columns(5)
            e1.metric("Active docs", emb_stats.get("active_documents", 0))
            e2.metric("Table docs", emb_stats.get("table_documents", 0))
            e3.metric("Column docs", emb_stats.get("column_documents", 0))
            e4.metric("Embeddings", emb_stats.get("embedding_count", 0))
            e5.metric("Stale docs", emb_stats.get("stale_documents", 0))
            st.caption(
                f"source_id={emb_stats.get('source_id')} · "
                f"source_name={emb_stats.get('source_name')}"
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Embedding stats 로드 실패: {exc}")

        try:
            summary_resp = api_get(f"/api/v1/targets/{tid}/catalog-summary")
            if summary_resp.ok:
                summary = summary_resp.json()
                st.markdown("#### Catalog Summary")
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Tables", summary.get("tables", 0))
                s2.metric("Columns", summary.get("columns", 0))
                s3.metric("Relations", summary.get("relations", 0))
                s4.metric("Indexes", summary.get("indexes", 0))
                st.caption(
                    f"source={summary.get('source_name')} · "
                    f"last_success_run={summary.get('last_success_run_id')} · "
                    f"fingerprint={summary.get('last_success_fingerprint')} · "
                    f"at={summary.get('last_success_at')}"
                )
            else:
                st.warning(f"Catalog summary 로드 실패: {summary_resp.text}")
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Catalog summary 오류: {exc}")

        try:
            tables_resp = api_get(
                "/api/v1/schema/tables",
                params={"source_id": tid, "active": "true"},
            )
            tables_resp.raise_for_status()
            tables = tables_resp.json()
        except Exception as exc:  # noqa: BLE001
            st.error(f"Table 목록 로드 실패: {exc}")
            tables = []

        st.markdown("#### Tables")
        f1, f2, f3 = st.columns(3)
        schema_filter = f1.text_input("Schema filter", key="explorer_schema_f")
        name_filter = f2.text_input("Table name filter", key="explorer_name_f")
        comment_filter = f3.text_input("Comment search", key="explorer_comment_f")

        filtered = tables
        if schema_filter.strip():
            q = schema_filter.strip().lower()
            filtered = [t for t in filtered if q in (t.get("schema_name") or "").lower()]
        if name_filter.strip():
            q = name_filter.strip().lower()
            filtered = [t for t in filtered if q in (t.get("table_name") or "").lower()]
        if comment_filter.strip():
            q = comment_filter.strip().lower()
            filtered = [t for t in filtered if q in (t.get("table_comment") or "").lower()]

        table_rows = [
            {
                "Schema": t.get("schema_name"),
                "Table": t.get("table_name"),
                "Comment": t.get("table_comment") or "",
                "Column Count": t.get("column_count", 0),
                "id": t.get("id"),
            }
            for t in filtered
        ]
        st.dataframe(
            [{k: v for k, v in r.items() if k != "id"} for r in table_rows],
            use_container_width=True,
        )
        st.caption(f"{len(filtered)} / {len(tables)} tables")

        if filtered:
            labels = [
                f"{t.get('schema_name')}.{t.get('table_name')} (id={t.get('id')})"
                for t in filtered
            ]
            choice = st.selectbox("Table 선택", labels, key="explorer_table_select")
            chosen = filtered[labels.index(choice)]
            try:
                detail_resp = api_get(f"/api/v1/schema/tables/{chosen['id']}")
                detail_resp.raise_for_status()
                detail = detail_resp.json()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Table detail 로드 실패: {exc}")
                detail = None

            if detail:
                st.markdown(
                    f"#### `{detail.get('schema_name')}.{detail.get('table_name')}`"
                )
                if detail.get("table_comment"):
                    st.write(detail["table_comment"])

                st.markdown("##### Columns")
                col_rows = [
                    {
                        "Name": c.get("column_name"),
                        "Type": c.get("data_type"),
                        "Nullable": c.get("nullable"),
                        "PK": c.get("primary_key"),
                        "Unique": c.get("unique"),
                        "Default": c.get("default_value"),
                        "Comment": c.get("comment") or "",
                    }
                    for c in detail.get("columns") or []
                ]
                st.dataframe(col_rows, use_container_width=True)

                st.markdown("##### Outbound FK")
                outbound = detail.get("outbound_relations") or []
                if outbound:
                    st.json(outbound)
                else:
                    st.write("(none)")

                st.markdown("##### Inbound FK")
                inbound = detail.get("inbound_relations") or []
                if inbound:
                    st.json(inbound)
                else:
                    st.write("(none)")

                st.markdown("##### Indexes")
                indexes = detail.get("indexes") or []
                if indexes:
                    ix_rows = [
                        {
                            "Name": ix.get("index_name"),
                            "Unique": ix.get("is_unique"),
                            "Method": ix.get("index_method"),
                            "Columns": ", ".join(ix.get("columns") or []),
                        }
                        for ix in indexes
                    ]
                    st.dataframe(ix_rows, use_container_width=True)
                else:
                    st.write("(none)")


# ---------------------------------------------------------------------------
# Tab 3: Schema Search
# ---------------------------------------------------------------------------

with tab_search:
    st.markdown("### Schema Search")
    search_target = target_selector(targets, key="search_target", required=True)
    if search_target:
        try:
            search_stats = api_get(
                "/api/v1/embeddings/stats",
                params={"source_id": search_target["id"]},
                timeout=10,
            ).json()
            st.caption(
                "Target embedding: "
                f"active={search_stats.get('active_documents')} · "
                f"table={search_stats.get('table_documents')} · "
                f"column={search_stats.get('column_documents')} · "
                f"embeddings={search_stats.get('embedding_count')} · "
                f"stale={search_stats.get('stale_documents')}"
            )
        except Exception:  # noqa: BLE001
            pass

    query = st.text_input(
        "자연어 Query",
        value="최근 간수치 검사 결과",
        placeholder="예: 최근 처방 약품 / 고혈압 진단 이력 / tb_lab_rst",
        key="search_query",
    )
    col_a, col_b, col_c = st.columns(3)
    mode = col_a.selectbox("Search Mode", ["hybrid", "semantic", "keyword"], index=0)
    object_type = col_b.selectbox("Object Type", ["ALL", "TABLE", "COLUMN"], index=0)
    top_k = col_c.slider("Top K", min_value=1, max_value=50, value=10)

    col_d, col_e, col_f = st.columns(3)
    expand_terms = col_d.checkbox("Medical Term Expansion", value=True)
    expand_relations = col_e.checkbox("FK Relation Expansion", value=True)
    max_hops = col_f.slider("Max Relation Hops", min_value=0, max_value=4, value=2)

    if st.button("Search", type="primary", key="btn_search"):
        if not search_target:
            st.error("Target을 선택하세요.")
        elif str(provider).lower() == "fake" and mode in {"semantic", "hybrid"}:
            st.error(
                "Fake embedding provider에서는 Semantic/Hybrid를 기본 차단합니다. "
                "Keyword 모드를 사용하세요."
            )
        else:
            with st.spinner("검색 중..."):
                try:
                    payload = {
                        "query": query,
                        "mode": mode,
                        "top_k": top_k,
                        "object_type": object_type,
                        "expand_terms": expand_terms,
                        "expand_relations": expand_relations,
                        "max_relation_hops": max_hops,
                        "debug": True,
                        "source_id": search_target["id"],
                    }
                    search_resp = api_post(
                        "/api/v1/search/schema",
                        json=payload,
                        timeout=180,
                    )
                    if search_resp.status_code >= 400:
                        st.error(search_resp.text)
                    else:
                        data = search_resp.json()
                        st.markdown("#### Query Expansion")
                        q = data.get("query", {})
                        st.write(
                            {
                                "original": q.get("original"),
                                "normalized": q.get("normalized"),
                                "matched_concepts": q.get("matched_concepts"),
                                "expanded_terms": q.get("expanded_terms"),
                            }
                        )
                        st.caption(
                            f"mode={data.get('mode')} model_key={data.get('model_key')} "
                            f"source_id={data.get('source_id')} "
                            f"source_name={data.get('source_name')} "
                            f"elapsed_ms={data.get('elapsed_ms'):.1f}"
                        )
                        if data.get("timings"):
                            st.json(data["timings"])

                        st.markdown("#### Direct Search Results")
                        for row in data.get("direct_results") or []:
                            schema = row.get("schema_name") or "public"
                            title = (
                                f"#{row.get('rank')} [{row.get('object_type')}] "
                                f"{schema}.{row.get('table_name')}"
                            )
                            if row.get("column_name"):
                                title += f".{row.get('column_name')}"
                            with st.expander(title, expanded=row.get("rank") == 1):
                                st.write(
                                    {
                                        "schema_name": row.get("schema_name"),
                                        "document_key": row.get("document_key"),
                                        "semantic_score": row.get("semantic_score"),
                                        "semantic_rank": row.get("semantic_rank"),
                                        "keyword_score": row.get("keyword_score"),
                                        "keyword_rank": row.get("keyword_rank"),
                                        "rrf_score": row.get("rrf_score"),
                                        "evidence": row.get("evidence"),
                                    }
                                )
                                st.code(row.get("searchable_snippet") or "", language="text")

                        st.markdown("#### Related Tables (FK Expansion)")
                        related = data.get("related_tables") or []
                        if not related:
                            st.write("(none)")
                        for rel in related:
                            seed = f"{rel.get('seed_schema')}.{rel.get('seed_table')}"
                            target = f"{rel.get('schema_name')}.{rel.get('table_name')}"
                            path = " → ".join(
                                [seed]
                                + [
                                    f"{h.get('to_schema')}.{h.get('to_table')}"
                                    for h in rel.get("relation_path") or []
                                ]
                            )
                            st.write(
                                f"- **{target}** (seed={seed}, "
                                f"hop={rel.get('hop_distance')}) path: `{path}`"
                            )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Search 호출 실패: {exc}")

    st.divider()
    with st.expander("검색 인덱스 유틸", expanded=False):
        src = (search_target or {}).get("source_name") if search_target else "medical_demo"
        st.caption(f"source query param = `{src}`")
        if st.button("Search Document Rebuild", key="search_util_rebuild"):
            r = api_post(
                f"/api/v1/embeddings/documents/rebuild?source={src}",
                timeout=300,
            )
            show_response(r)
        if st.button("Embedding Run", key="search_util_embed"):
            r = api_post(f"/api/v1/embeddings/run?source={src}", timeout=3600)
            show_response(r)


# ---------------------------------------------------------------------------
# Tab 4: Validation Results
# ---------------------------------------------------------------------------

with tab_eval:
    st.markdown("### 검증 결과")
    st.caption("저장된 검색 평가 결과를 조회합니다. UI에서 장시간 평가를 실행하지 않습니다.")
    default_root = os.getenv("EVALUATION_RESULTS_DIR", "/app/evaluation/results")
    root = st.text_input("Results root", value=default_root)
    run_dirs = []
    if os.path.isdir(root):
        run_dirs = sorted(
            [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))],
            reverse=True,
        )
    if not run_dirs:
        st.warning("평가 결과 디렉터리가 없습니다. CLI runner로 평가를 먼저 실행하세요.")
    else:
        run_name = st.selectbox("Run", run_dirs)
        run_path = os.path.join(root, run_name)
        summary_path = os.path.join(run_path, "summary.json")
        query_csv = os.path.join(run_path, "query_results.csv")
        fail_csv = os.path.join(run_path, "failures.csv")
        meta_path = os.path.join(run_path, "run_metadata.json")
        if os.path.exists(meta_path):
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            st.json(
                {
                    "executed_at": meta.get("executed_at"),
                    "model_key": meta.get("model_key"),
                    "query_count": meta.get("query_count"),
                    "git_commit": meta.get("git_commit"),
                }
            )
        if os.path.exists(summary_path):
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)
            exps = summary.get("experiments") or []
            if exps:
                st.markdown("#### Experiment Comparison")
                st.dataframe(exps, use_container_width=True)
                chart_rows = [
                    {
                        "experiment": e.get("experiment"),
                        "Hit@5": e.get("hit_rate_at_5"),
                        "MRR": e.get("mrr"),
                        "AvgLatency": e.get("avg_total_ms"),
                    }
                    for e in exps
                ]
                st.bar_chart(
                    {
                        "Hit@5": {r["experiment"]: r["Hit@5"] for r in chart_rows},
                    }
                )
                st.bar_chart(
                    {
                        "MRR": {r["experiment"]: r["MRR"] for r in chart_rows},
                    }
                )
                st.bar_chart(
                    {
                        "AvgLatency(ms)": {r["experiment"]: r["AvgLatency"] for r in chart_rows},
                    }
                )
            if summary.get("notes"):
                st.markdown("#### Notes")
                for line in summary["notes"]:
                    st.write(f"- {line}")
            cats = summary.get("categories") or []
            if cats:
                st.markdown("#### Category Metrics")
                st.dataframe(cats, use_container_width=True)
        if os.path.exists(fail_csv):
            st.markdown("#### Failure Queries")
            try:
                with open(fail_csv, encoding="utf-8") as f:
                    fails = list(csv.DictReader(f))
                st.dataframe(fails[:100], use_container_width=True)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"failures.csv 로드 실패: {exc}")
        if os.path.exists(query_csv):
            st.markdown("#### Query Detail")
            try:
                with open(query_csv, encoding="utf-8") as f:
                    qrows = list(csv.DictReader(f))
                qids = sorted({r["query_id"] for r in qrows})
                qid = st.selectbox("Query ID", qids)
                exp = st.selectbox("Experiment", sorted({r["experiment"] for r in qrows}))
                matches = [r for r in qrows if r["query_id"] == qid and r["experiment"] == exp]
                if matches:
                    row = matches[0]
                    st.write(
                        {
                            "query": row.get("query"),
                            "category": row.get("category"),
                            "matched_concepts": row.get("matched_concepts"),
                            "top1_table": row.get("top1_table"),
                            "top3_tables": row.get("top3_tables"),
                            "top5_tables": row.get("top5_tables"),
                            "primary_hit_top1": row.get("primary_hit_top1"),
                            "relevant_hit_top3": row.get("relevant_hit_top3"),
                            "relevant_hit_top5": row.get("relevant_hit_top5"),
                            "reciprocal_rank": row.get("reciprocal_rank"),
                            "total_ms": row.get("total_ms"),
                            "query_embedding_ms": row.get("query_embedding_ms"),
                            "semantic_search_ms": row.get("semantic_search_ms"),
                            "keyword_search_ms": row.get("keyword_search_ms"),
                            "relation_expansion_ms": row.get("relation_expansion_ms"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                st.warning(f"query_results.csv 로드 실패: {exc}")
