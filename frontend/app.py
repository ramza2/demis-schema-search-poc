"""Streamlit UI — Multi-DB Target Analyzer + Schema Explorer."""

from __future__ import annotations

import csv
import json
import os
from typing import Any

import requests
import streamlit as st

from helpers import (
    DISCOVER_SCHEMAS_TIMEOUT_SECONDS,
    HOST_INPUT_HINT,
    LOAD_TARGETS_TIMEOUT_SECONDS,
    TEST_CONNECTION_TIMEOUT_SECONDS,
    credential_status_label,
    format_connection_request_error,
)

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

DEFAULT_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "oracle": 1521,
}


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
        st.info("등록된 Target이 없습니다. Targets 탭에서 추가하세요.")
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


# ---------------------------------------------------------------------------
# Page setup + shared header
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="DEMIS Schema Semantic Search PoC",
    page_icon="🏥",
    layout="wide",
)

st.title("DEMIS Schema Semantic Search PoC")
st.subheader("Multi-DB Target Analyzer + Schema Explorer")
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
    if health.get("medical_db_required") is False:
        st.caption("medical_demo는 optional(disabled 가능). catalog/backend만 health 필수입니다.")
    st.caption(f"step={health.get('step', '')} · status={health.get('status', '')}")
except Exception as exc:  # noqa: BLE001
    st.error(f"Backend 연결 실패: {exc}")
    st.stop()

provider = "unknown"
try:
    stats = api_get("/api/v1/embeddings/stats", timeout=10).json()
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

# Create tabs before Target API calls so navigation stays available on timeouts.
tab_targets, tab_explorer, tab_search, tab_eval = st.tabs(
    ["Targets", "Schema Explorer", "Schema Search", "Evaluation Results"]
)
targets, targets_load_error = load_targets()


# ---------------------------------------------------------------------------
# Tab 1: Targets
# ---------------------------------------------------------------------------

with tab_targets:
    st.markdown("### Target 목록")
    if targets_load_error:
        st.warning(f"Target 목록을 불러오지 못했습니다: {targets_load_error}")
    if targets:
        rows = [
            {
                "Name": t.get("source_name"),
                "DBMS": t.get("db_type"),
                "Host": t.get("host"),
                "Port": t.get("port"),
                "Database": t.get("database_name"),
                "Default Schema": t.get("default_schema"),
                "Username": t.get("username"),
                "Credential": credential_status_label(bool(t.get("has_saved_password"))),
                "Enabled": t.get("enabled"),
            }
            for t in targets
        ]
        st.dataframe(rows, use_container_width=True)
    else:
        st.write("(등록된 Target 없음)")

    st.markdown("### Target 추가")
    db_type = st.selectbox(
        "DB Type",
        ["postgresql", "mysql", "mariadb", "oracle"],
        key="add_target_db_type",
    )
    port = st.number_input(
        "Port",
        min_value=1,
        max_value=65535,
        value=DEFAULT_PORTS.get(db_type, 5432),
        key=f"add_target_port_{db_type}",
    )
    with st.form("add_target_form", clear_on_submit=True):
        source_name = st.text_input("Source Name", placeholder="my_target")
        host = st.text_input("Host", value="localhost")
        st.caption(HOST_INPUT_HINT)
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        st.caption("Password는 Catalog DB에 암호화되어 저장됩니다. 평문으로는 저장/표시되지 않습니다.")

        database_name = ""
        default_schema = "public"
        service_name = ""
        connection_options: dict[str, Any] | None = None

        if db_type == "postgresql":
            database_name = st.text_input("Database", value="")
            default_schema = st.text_input("Schema", value="public")
        elif db_type in {"mysql", "mariadb"}:
            database_name = st.text_input("Database", value="")
            st.caption("MySQL/MariaDB: default_schema는 database 이름과 동일하게 저장됩니다.")
        else:  # oracle
            service_name = st.text_input("Service Name", value="")
            default_schema = st.text_input("Schema / Owner", value="")

        enabled = st.checkbox("Enabled", value=True)
        submitted = st.form_submit_button("Add Target", type="primary")

        if submitted:
            if db_type in {"mysql", "mariadb"}:
                default_schema = database_name
            if db_type == "oracle":
                database_name = service_name
                connection_options = {"service_name": service_name} if service_name else None
            missing = []
            if not source_name.strip():
                missing.append("source_name")
            if not host.strip():
                missing.append("host")
            if not str(database_name).strip():
                missing.append("database/service_name")
            if not str(default_schema).strip():
                missing.append("default_schema")
            if not username.strip():
                missing.append("username")
            if not password:
                missing.append("password")
            if missing:
                st.error(f"필수 항목 누락: {', '.join(missing)}")
            else:
                payload = {
                    "source_name": source_name.strip(),
                    "db_type": db_type,
                    "host": host.strip(),
                    "port": int(port),
                    "database_name": str(database_name).strip(),
                    "default_schema": str(default_schema).strip(),
                    "username": username.strip(),
                    "password": password,
                    "connection_options": connection_options,
                    "enabled": enabled,
                }
                try:
                    create_resp = api_post("/api/v1/targets", json=payload, timeout=30)
                    show_response(create_resp)
                    if create_resp.ok:
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Target 생성 실패: {exc}")

    st.markdown("### 선택 Target 작업")
    selected = target_selector(targets, key="targets_action_select")
    if selected:
        st.caption(f"id={selected['id']} · {target_label(selected)}")
        has_saved = bool(selected.get("has_saved_password"))
        st.info(
            f"Credential: **{credential_status_label(has_saved)}**"
            + (" — Test / Discover / Analyze 시 저장된 비밀번호를 사용합니다." if has_saved else "")
        )
        temp_password = ""
        if not has_saved:
            st.warning("저장된 Credential이 없습니다. 아래에서 임시 Password를 입력하거나 Edit Target에서 등록하세요.")
            temp_password = st.text_input(
                "임시 Password (이 요청에만 사용, 저장되지 않음)",
                type="password",
                key="target_action_temp_password",
            )

        with st.expander("Edit Target", expanded=False):
            edit_db_type = st.selectbox(
                "DB Type",
                ["postgresql", "mysql", "mariadb", "oracle"],
                index=["postgresql", "mysql", "mariadb", "oracle"].index(
                    selected.get("db_type") or "postgresql"
                ),
                key=f"edit_db_type_{selected['id']}",
            )
            with st.form(f"edit_target_form_{selected['id']}"):
                edit_name = st.text_input("Source Name", value=selected.get("source_name") or "")
                edit_host = st.text_input("Host", value=selected.get("host") or "")
                st.caption(HOST_INPUT_HINT)
                edit_port = st.number_input(
                    "Port",
                    min_value=1,
                    max_value=65535,
                    value=int(selected.get("port") or DEFAULT_PORTS.get(edit_db_type, 5432)),
                )
                edit_username = st.text_input("Username", value=selected.get("username") or "")
                edit_database = st.text_input(
                    "Database / Service Name",
                    value=selected.get("database_name") or "",
                )
                edit_schema = st.text_input(
                    "Default Schema / Owner",
                    value=selected.get("default_schema") or "",
                )
                st.caption(
                    f"Saved credential: {'있음' if has_saved else '없음'} — "
                    "새 Password를 입력하면 기존 Credential을 교체합니다. 비워두면 유지합니다."
                )
                edit_password = st.text_input(
                    "Password (새 비밀번호 입력 시 기존 credential 교체)",
                    type="password",
                    key=f"edit_password_{selected['id']}",
                )
                clear_saved = st.checkbox(
                    "저장된 Credential 삭제",
                    value=False,
                    key=f"edit_clear_cred_{selected['id']}",
                )
                edit_enabled = st.checkbox(
                    "Enabled",
                    value=bool(selected.get("enabled", True)),
                    key=f"edit_enabled_{selected['id']}",
                )
                save_edit = st.form_submit_button("Save Target", type="primary")
                if save_edit:
                    update_payload: dict[str, Any] = {
                        "source_name": edit_name.strip(),
                        "db_type": edit_db_type,
                        "host": edit_host.strip(),
                        "port": int(edit_port),
                        "database_name": edit_database.strip(),
                        "default_schema": edit_schema.strip() or "public",
                        "username": edit_username.strip(),
                        "enabled": edit_enabled,
                        "clear_saved_password": clear_saved,
                    }
                    if edit_db_type == "oracle":
                        update_payload["connection_options"] = (
                            {"service_name": edit_database.strip()}
                            if edit_database.strip()
                            else None
                        )
                    if edit_password and not clear_saved:
                        update_payload["password"] = edit_password
                    try:
                        upd = api_put(
                            f"/api/v1/targets/{selected['id']}",
                            json=update_payload,
                            timeout=30,
                        )
                        show_response(upd)
                        if upd.ok:
                            st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Target 수정 실패: {exc}")

        def _action_password_payload() -> dict[str, str] | None:
            if has_saved:
                return {}
            if temp_password:
                return {"password": temp_password}
            return None

        b1, b2 = st.columns(2)
        with b1:
            if st.button("Test Connection", key="btn_test_conn"):
                body = _action_password_payload()
                if body is None:
                    st.error("저장된 Credential이 없습니다. 임시 Password를 입력하세요.")
                else:
                    try:
                        r = api_post(
                            f"/api/v1/targets/{selected['id']}/test",
                            json=body,
                            timeout=TEST_CONNECTION_TIMEOUT_SECONDS,
                        )
                        show_response(r)
                    except Exception as exc:  # noqa: BLE001
                        st.error(format_connection_request_error(exc))
        with b2:
            if st.button("Discover Schemas", key="btn_discover"):
                body = _action_password_payload()
                if body is None:
                    st.error("저장된 Credential이 없습니다. 임시 Password를 입력하세요.")
                else:
                    try:
                        r = api_post(
                            f"/api/v1/targets/{selected['id']}/schemas",
                            json=body,
                            timeout=DISCOVER_SCHEMAS_TIMEOUT_SECONDS,
                        )
                        show_response(r)
                        if r.ok:
                            st.session_state[f"discovered_schemas_{selected['id']}"] = (
                                r.json().get("schemas") or []
                            )
                    except Exception as exc:  # noqa: BLE001
                        st.error(format_connection_request_error(exc))

        discovered = st.session_state.get(f"discovered_schemas_{selected['id']}", [])
        schema_options = discovered or (
            [selected.get("default_schema")] if selected.get("default_schema") else []
        )
        chosen_schemas = st.multiselect(
            "Schemas to Analyze",
            options=schema_options,
            default=schema_options[:1] if schema_options else [],
            key=f"analyze_schemas_{selected['id']}",
        )
        if st.button("Analyze", type="primary", key="btn_analyze"):
            body = _action_password_payload()
            if body is None:
                st.error("저장된 Credential이 없습니다. 임시 Password를 입력하세요.")
            elif not chosen_schemas:
                st.error("분석할 Schema를 선택하세요.")
            else:
                try:
                    payload = {"schemas": chosen_schemas}
                    if body.get("password"):
                        payload["password"] = body["password"]
                    r = api_post(
                        f"/api/v1/targets/{selected['id']}/analyze",
                        json=payload,
                        timeout=600,
                    )
                    show_response(r)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Analyze 실패: {exc}")

        st.markdown("#### Embedding Pipeline")
        source_name = selected.get("source_name") or ""
        e1, e2 = st.columns(2)
        with e1:
            if st.button("Rebuild Docs", key="btn_rebuild_docs"):
                try:
                    r = api_post(
                        f"/api/v1/embeddings/documents/rebuild?source={source_name}",
                        timeout=300,
                    )
                    show_response(r)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Rebuild Docs 실패: {exc}")
        with e2:
            if st.button("Embedding Run", key="btn_embed_run"):
                try:
                    r = api_post(
                        f"/api/v1/embeddings/run?source={source_name}",
                        timeout=3600,
                    )
                    show_response(r)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Embedding Run 실패: {exc}")

        st.markdown("#### Delete Target")
        st.warning("삭제하면 이 Target의 Catalog / Search Document / Embedding 데이터가 함께 제거됩니다.")
        confirm_name = st.text_input(
            "삭제 확인: Source Name을 다시 입력하세요",
            key=f"delete_confirm_{selected['id']}",
        )
        if st.button("Delete Target", type="secondary", key="btn_delete_target"):
            if confirm_name.strip() != (selected.get("source_name") or ""):
                st.error("Source Name이 일치하지 않습니다. 삭제가 취소되었습니다.")
            else:
                try:
                    r = api_delete(f"/api/v1/targets/{selected['id']}", timeout=60)
                    if r.status_code == 204:
                        st.rerun()
                    else:
                        show_response(r)
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Target 삭제 실패: {exc}")

    st.markdown("### medical_demo Analyze Shortcut")
    st.caption("기본 medical_demo 소스에 대해 POST /api/v1/schema/analyze 를 호출합니다.")
    if st.button("Analyze medical_demo", key="btn_medical_demo_analyze"):
        try:
            r = api_post("/api/v1/schema/analyze", timeout=120)
            show_response(r)
        except Exception as exc:  # noqa: BLE001
            st.error(f"medical_demo analyze 실패: {exc}")


# ---------------------------------------------------------------------------
# Tab 2: Schema Explorer
# ---------------------------------------------------------------------------

with tab_explorer:
    st.markdown("### Schema Explorer")
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
    with st.expander("Pipeline 유틸 (Analyze / Rebuild / Embed)", expanded=False):
        src = (search_target or {}).get("source_name") if search_target else "medical_demo"
        st.caption(f"source query param = `{src}`")
        if st.button("Schema Analyze (medical_demo)", key="search_util_analyze"):
            r = api_post("/api/v1/schema/analyze", timeout=120)
            show_response(r)
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
# Tab 4: Evaluation Results
# ---------------------------------------------------------------------------

with tab_eval:
    st.markdown("### Evaluation Result Viewer")
    st.caption("저장된 Step 5 평가 결과를 조회합니다. UI에서 BGE 평가를 장시간 실행하지 않습니다.")
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
