"""Dedicated Table Explorer UI for DEMIS Schema Analyzer."""

from __future__ import annotations

from typing import Any, Callable

import requests
import streamlit as st


ApiGet = Callable[..., requests.Response]


def filter_tables(
    tables: list[dict[str, Any]],
    *,
    schema_query: str = "",
    text_query: str = "",
    allowed_table_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Filter active catalog tables without changing source order."""
    schema_q = schema_query.strip().lower()
    text_q = text_query.strip().lower()
    result: list[dict[str, Any]] = []
    for table in tables:
        table_id = table.get("id")
        if allowed_table_ids is not None and table_id not in allowed_table_ids:
            continue
        if schema_q and schema_q not in str(table.get("schema_name") or "").lower():
            continue
        if text_q:
            haystack = " ".join(
                [
                    str(table.get("table_name") or ""),
                    str(table.get("table_comment") or ""),
                ]
            ).lower()
            if text_q not in haystack:
                continue
        result.append(table)
    return result


def column_rows(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "#": col.get("ordinal_position"),
            "Column": col.get("column_name"),
            "Type": col.get("data_type"),
            "Nullable": col.get("nullable"),
            "PK": col.get("primary_key"),
            "Unique": col.get("unique"),
            "Default": col.get("default_value"),
            "Comment": col.get("comment") or "",
        }
        for col in detail.get("columns") or []
    ]


def relation_rows(relations: list[dict[str, Any]], *, direction: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rel in relations:
        mapping = ", ".join(
            f"{item.get('source')} → {item.get('target')}"
            for item in rel.get("column_mapping") or []
        )
        related = rel.get("target_table") if direction == "outbound" else rel.get("source_table")
        rows.append(
            {
                "Constraint": rel.get("constraint"),
                "Related Table": related,
                "Type": rel.get("relation_type"),
                "Column Mapping": mapping,
            }
        )
    return rows


def index_rows(detail: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Index": ix.get("index_name"),
            "Unique": ix.get("is_unique"),
            "Method": ix.get("index_method"),
            "Columns": ", ".join(ix.get("columns") or []),
        }
        for ix in detail.get("indexes") or []
    ]


def _load_json(api_get: ApiGet, path: str, **kwargs: Any) -> Any:
    response = api_get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def render_table_explorer(
    *,
    targets: list[dict[str, Any]],
    api_get: ApiGet,
) -> None:
    """Render read-only table/category/relationship exploration for one Target."""
    st.title("Table Explorer")
    st.caption("분석된 DB Catalog의 Table·Column·관계·Index·Category를 한 화면에서 탐색합니다.")

    if not targets:
        st.info("등록된 Target이 없습니다. DEMIS Schema Analyzer의 DB Targets에서 먼저 등록하세요.")
        return

    labels = [
        f"{target.get('source_name')} / {target.get('db_type')} / {target.get('database_name')}"
        for target in targets
    ]
    selected_label = st.selectbox("Target", labels, key="table_explorer_target")
    target = targets[labels.index(selected_label)]
    source_id = int(target["id"])

    summary: dict[str, Any] = {}
    try:
        summary = _load_json(api_get, f"/api/v1/targets/{source_id}/catalog-summary")
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Catalog Summary 로드 실패: {exc}")

    try:
        categories = _load_json(
            api_get,
            "/api/v1/catalog/categories",
            params={"source_id": source_id, "active": "true"},
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Category 로드 실패: {exc}")
        categories = []

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Tables", summary.get("tables", 0))
    m2.metric("Columns", summary.get("columns", 0))
    m3.metric("Relations", summary.get("relations", 0))
    m4.metric("Indexes", summary.get("indexes", 0))
    m5.metric("Categories", len(categories))
    if summary:
        st.caption(
            f"source={summary.get('source_name')} · "
            f"last_success_run={summary.get('last_success_run_id')} · "
            f"fingerprint={summary.get('last_success_fingerprint')}"
        )

    try:
        tables = _load_json(
            api_get,
            "/api/v1/schema/tables",
            params={"source_id": source_id, "active": "true"},
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Table 목록 로드 실패: {exc}")
        return

    category_by_label: dict[str, dict[str, Any]] = {
        f"{item.get('category_name')} ({item.get('table_count', 0)})": item for item in categories
    }
    category_options = ["전체"] + list(category_by_label)

    f1, f2, f3 = st.columns([1, 1, 2])
    category_choice = f1.selectbox("Category", category_options, key="table_explorer_category")
    schema_options = ["전체"] + sorted(
        {str(table.get("schema_name") or "") for table in tables if table.get("schema_name")}
    )
    schema_choice = f2.selectbox("Schema", schema_options, key="table_explorer_schema")
    text_query = f3.text_input(
        "Table / Comment 검색",
        placeholder="예: TB_PT_MST, 환자, 진료",
        key="table_explorer_query",
    )

    allowed_ids: set[int] | None = None
    if category_choice != "전체":
        category = category_by_label[category_choice]
        try:
            assigned = _load_json(
                api_get,
                f"/api/v1/catalog/categories/{category['id']}/tables",
            )
            allowed_ids = {int(item["table_id"]) for item in assigned}
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Category Table 목록 로드 실패: {exc}")
            allowed_ids = set()

    filtered = filter_tables(
        tables,
        schema_query="" if schema_choice == "전체" else schema_choice,
        text_query=text_query,
        allowed_table_ids=allowed_ids,
    )

    st.markdown("### Tables")
    rows = [
        {
            "Schema": table.get("schema_name"),
            "Table": table.get("table_name"),
            "Comment": table.get("table_comment") or "",
            "Columns": table.get("column_count", 0),
            "Type": table.get("table_type"),
        }
        for table in filtered
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"{len(filtered)} / {len(tables)} tables")

    if not filtered:
        st.info("조건에 맞는 Table이 없습니다.")
        return

    labels = [
        f"{table.get('schema_name')}.{table.get('table_name')} — {table.get('table_comment') or '설명 없음'}"
        for table in filtered
    ]
    selected = st.selectbox("Table 선택", labels, key="table_explorer_table")
    table = filtered[labels.index(selected)]

    try:
        detail = _load_json(api_get, f"/api/v1/schema/tables/{table['id']}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Table 상세 로드 실패: {exc}")
        return

    try:
        table_categories = _load_json(
            api_get,
            f"/api/v1/catalog/tables/{table['id']}/categories",
        )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Table Category 로드 실패: {exc}")
        table_categories = []

    st.divider()
    st.markdown(f"## `{detail.get('schema_name')}.{detail.get('table_name')}`")
    st.write(detail.get("table_comment") or "DB COMMENT가 없습니다.")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Columns", len(detail.get("columns") or []))
    d2.metric("Outbound FK", len(detail.get("outbound_relations") or []))
    d3.metric("Inbound FK", len(detail.get("inbound_relations") or []))
    d4.metric("Indexes", len(detail.get("indexes") or []))

    tab_columns, tab_relations, tab_indexes, tab_categories = st.tabs(
        ["Columns", "Relations", "Indexes", "Categories"]
    )

    with tab_columns:
        st.dataframe(column_rows(detail), use_container_width=True, hide_index=True)

    with tab_relations:
        st.markdown("#### Outbound FK")
        outbound_rows = relation_rows(detail.get("outbound_relations") or [], direction="outbound")
        if outbound_rows:
            st.dataframe(outbound_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("Outbound FK가 없습니다.")
        st.markdown("#### Inbound FK")
        inbound_rows = relation_rows(detail.get("inbound_relations") or [], direction="inbound")
        if inbound_rows:
            st.dataframe(inbound_rows, use_container_width=True, hide_index=True)
        else:
            st.caption("Inbound FK가 없습니다.")

    with tab_indexes:
        rows = index_rows(detail)
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.caption("Index가 없습니다.")

    with tab_categories:
        if table_categories:
            st.dataframe(
                [
                    {
                        "Category": item.get("category_name"),
                        "Key": item.get("category_key"),
                        "Primary": item.get("is_primary"),
                        "Source": item.get("assignment_source"),
                        "Confidence": item.get("confidence"),
                        "Note": item.get("note") or "",
                    }
                    for item in table_categories
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("지정된 Category가 없습니다.")

    with st.expander("기술 정보", expanded=False):
        st.json(
            {
                "table_id": detail.get("id"),
                "table_type": detail.get("table_type"),
                "active": detail.get("active"),
                "object_fingerprint": detail.get("object_fingerprint"),
            }
        )
