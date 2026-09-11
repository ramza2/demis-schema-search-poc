"""Streamlit UI for Step 4 — Schema Search (no NL→SQL)."""

from __future__ import annotations

import os

import requests
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="DEMIS Schema Semantic Search PoC",
    page_icon="🏥",
    layout="wide",
)

st.title("DEMIS Schema Semantic Search PoC")
st.subheader("현재 Step: Step 4 - Semantic/Keyword Hybrid Search + Terminology + FK Expansion")
st.write(
    "자연어로 Schema(Table/Column)를 탐색합니다. "
    "생성형 LLM 및 자연어→SQL 생성은 포함하지 않습니다."
)

st.divider()
st.markdown("### 서비스 상태")

try:
    resp = requests.get(f"{BACKEND_URL}/health", timeout=5)
    resp.raise_for_status()
    health = resp.json()
    st.success(f"Backend 연결 성공 (`{BACKEND_URL}`)")
    c1, c2, c3 = st.columns(3)
    c1.metric("Backend", health.get("backend", "unknown"))
    c2.metric("medical_demo", health.get("medical_db", "unknown"))
    c3.metric("schema_catalog", health.get("catalog_db", "unknown"))
    st.caption(f"step={health.get('step', '')}")
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.stop()

# Provider / stats
provider = "unknown"
try:
    stats = requests.get(f"{BACKEND_URL}/api/v1/embeddings/stats", timeout=10).json()
    provider = stats.get("embedding_provider") or stats.get("provider") or "unknown"
    st.info(
        f"Embedding provider=`{provider}` device=`{stats.get('embedding_device', '?')}` "
        f"dim=`{stats.get('embedding_dimension', '?')}` "
        f"docs=`{stats.get('active_documents', '?')}` embeddings=`{stats.get('embedding_count', '?')}`"
    )
    if str(provider).lower() == "fake":
        st.warning(
            "Fake Embedding — Test only. Semantic/Hybrid 검색은 "
            "ALLOW_FAKE_SEMANTIC_SEARCH=true 일 때만 허용됩니다. Keyword 모드는 사용 가능합니다."
        )
except Exception:  # noqa: BLE001
    pass

st.divider()
st.markdown("### Schema Search")

query = st.text_input(
    "자연어 Query",
    value="최근 간수치 검사 결과",
    placeholder="예: 최근 처방 약품 / 고혈압 진단 이력 / tb_lab_rst",
)
col_a, col_b, col_c = st.columns(3)
mode = col_a.selectbox("Search Mode", ["hybrid", "semantic", "keyword"], index=0)
object_type = col_b.selectbox("Object Type", ["ALL", "TABLE", "COLUMN"], index=0)
top_k = col_c.slider("Top K", min_value=1, max_value=50, value=10)

col_d, col_e, col_f = st.columns(3)
expand_terms = col_d.checkbox("Medical Term Expansion", value=True)
expand_relations = col_e.checkbox("FK Relation Expansion", value=True)
max_hops = col_f.slider("Max Relation Hops", min_value=0, max_value=4, value=2)

if st.button("Search", type="primary"):
    if str(provider).lower() == "fake" and mode in {"semantic", "hybrid"}:
        st.error("Fake embedding provider에서는 Semantic/Hybrid를 기본 차단합니다. Keyword 모드를 사용하세요.")
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
                }
                search_resp = requests.post(
                    f"{BACKEND_URL}/api/v1/search/schema",
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
                        f"elapsed_ms={data.get('elapsed_ms'):.1f}"
                    )
                    if data.get("timings"):
                        st.json(data["timings"])

                    st.markdown("#### Direct Search Results")
                    for row in data.get("direct_results") or []:
                        title = f"#{row.get('rank')} [{row.get('object_type')}] {row.get('table_name')}"
                        if row.get("column_name"):
                            title += f".{row.get('column_name')}"
                        with st.expander(title, expanded=row.get("rank") == 1):
                            st.write(
                                {
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
                        path = " → ".join(
                            [rel.get("seed_table")]
                            + [h.get("to_table") for h in rel.get("relation_path") or []]
                        )
                        st.write(
                            f"- **{rel.get('table_name')}** (seed={rel.get('seed_table')}, "
                            f"hop={rel.get('hop_distance')}) path: `{path}`"
                        )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Search 호출 실패: {exc}")

st.divider()
with st.expander("Pipeline 유틸 (Analyze / Rebuild / Embed)", expanded=False):
    if st.button("Schema Analyze"):
        r = requests.post(f"{BACKEND_URL}/api/v1/schema/analyze", timeout=120)
        st.json(r.json() if r.ok else {"error": r.text})
    if st.button("Search Document Rebuild"):
        r = requests.post(f"{BACKEND_URL}/api/v1/embeddings/documents/rebuild", timeout=120)
        st.json(r.json() if r.ok else {"error": r.text})
    if st.button("Embedding Run"):
        r = requests.post(f"{BACKEND_URL}/api/v1/embeddings/run", timeout=3600)
        st.json(r.json() if r.ok else {"error": r.text})
