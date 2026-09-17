"""Interactive ERD Explorer for DEMIS Schema Analyzer."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Callable

import requests
import streamlit as st
import streamlit.components.v1 as components

ApiGet = Callable[..., requests.Response]
_COMPONENT_NAME = "demis_erd_react_flow"
_COMPONENT_DIST = Path(__file__).resolve().parent / "erd_component" / "dist"


def build_adjacency(edges: list[dict[str, Any]]) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {}
    for edge in edges:
        source_id = int(edge["source_id"])
        target_id = int(edge["target_id"])
        adjacency.setdefault(source_id, set()).add(target_id)
        adjacency.setdefault(target_id, set()).add(source_id)
    return adjacency


def hop_distances(
    selected_id: int | None,
    edges: list[dict[str, Any]],
    *,
    max_hops: int = 2,
) -> dict[int, int]:
    if selected_id is None:
        return {}
    adjacency = build_adjacency(edges)
    distances = {int(selected_id): 0}
    queue: deque[int] = deque([int(selected_id)])
    while queue:
        current = queue.popleft()
        if distances[current] >= max_hops:
            continue
        for neighbor in sorted(adjacency.get(current, set())):
            if neighbor in distances:
                continue
            distances[neighbor] = distances[current] + 1
            queue.append(neighbor)
    return distances


def filter_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    mode: str,
    selected_id: int | None = None,
    max_hops: int = 2,
    category_id: int | None = None,
    text_query: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[int, int]]:
    distances = hop_distances(selected_id, edges, max_hops=max_hops)
    query = text_query.strip().lower()
    visible_ids: set[int] = set()

    for node in nodes:
        node_id = int(node["id"])
        if mode == "neighborhood" and node_id not in distances:
            continue
        if mode == "category":
            category_ids = {int(item["id"]) for item in node.get("categories") or []}
            if category_id is None or category_id not in category_ids:
                continue
        if query:
            haystack = " ".join(
                [
                    str(node.get("schema_name") or ""),
                    str(node.get("table_name") or ""),
                    str(node.get("table_comment") or ""),
                ]
            ).lower()
            if query not in haystack:
                continue
        visible_ids.add(node_id)

    visible_nodes = [node for node in nodes if int(node["id"]) in visible_ids]
    visible_edges = [
        edge
        for edge in edges
        if int(edge["source_id"]) in visible_ids and int(edge["target_id"]) in visible_ids
    ]
    return visible_nodes, visible_edges, distances


def relation_rows(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for edge in edges:
        mapping = ", ".join(
            f"{item.get('source')} → {item.get('target')}"
            for item in edge.get("column_mapping") or []
        )
        rows.append(
            {
                "Constraint": edge.get("constraint"),
                "Source": edge.get("source_table_key"),
                "Target": edge.get("target_table_key"),
                "Mapping": mapping,
            }
        )
    return rows


def build_component_payload(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    mode: str,
    selected_id: int | None,
    distances: dict[int, int],
    frame_height: int = 760,
) -> dict[str, Any]:
    """Build a JSON-safe contract for the React Flow + ELK component."""
    return {
        "nodes": nodes,
        "edges": edges,
        "selectedId": selected_id,
        "distances": {str(node_id): distance for node_id, distance in distances.items()},
        "mode": mode,
        # Full ERD intentionally hides FK labels; details remain in the table below.
        "showEdgeLabels": mode == "neighborhood",
        "frameHeight": frame_height,
    }


def _erd_component():
    if not (_COMPONENT_DIST / "index.html").exists():
        raise RuntimeError(
            "ERD React component build artifact not found. "
            "Build frontend/erd_component before starting Streamlit."
        )
    return components.declare_component(_COMPONENT_NAME, path=str(_COMPONENT_DIST))


def _load_json(api_get: ApiGet, path: str, **kwargs: Any) -> Any:
    response = api_get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def render_erd_explorer(*, targets: list[dict[str, Any]], api_get: ApiGet) -> None:
    st.title("ERD Explorer")
    st.caption(
        "React Flow + ELK.js로 Table 관계를 자동 배치하고, "
        "전체·Category·선택 Table 주변 관점으로 탐색합니다."
    )

    if not targets:
        st.info("등록된 Target이 없습니다. DB Targets에서 먼저 등록하세요.")
        return

    target_labels = [
        f"{target.get('source_name')} / {target.get('db_type')} / {target.get('database_name')}"
        for target in targets
    ]
    target_label = st.selectbox("Target", target_labels, key="erd_target")
    target = targets[target_labels.index(target_label)]
    source_id = int(target["id"])

    try:
        graph = _load_json(api_get, "/api/v1/schema/erd", params={"source_id": source_id})
    except Exception as exc:  # noqa: BLE001
        st.error(f"ERD 데이터 로드 실패: {exc}")
        return

    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    categories = graph.get("categories") or []
    counts = graph.get("counts") or {}

    m1, m2, m3 = st.columns(3)
    m1.metric("Tables", counts.get("nodes", len(nodes)))
    m2.metric("Relations", counts.get("edges", len(edges)))
    m3.metric("Categories", counts.get("categories", len(categories)))

    mode_labels = {
        "전체 ERD": "full",
        "선택 Table 주변": "neighborhood",
        "Category ERD": "category",
    }
    c1, c2, c3 = st.columns([1.2, 1.8, 2])
    mode_label = c1.selectbox("View", list(mode_labels), key="erd_view")
    mode = mode_labels[mode_label]

    focus_options = ["포커스 없음"] + [
        f"{node.get('table_key')} — {node.get('table_comment') or '설명 없음'}" for node in nodes
    ]
    focus_label = c2.selectbox("Focus Table", focus_options, key="erd_focus")
    selected_id: int | None = None
    if focus_label != "포커스 없음":
        selected_id = int(nodes[focus_options.index(focus_label) - 1]["id"])

    text_query = c3.text_input(
        "Table / Comment 검색",
        placeholder="예: 환자, TB_LAB_RST",
        key="erd_query",
    )

    max_hops = 2
    category_id: int | None = None
    if mode == "neighborhood":
        if selected_id is None:
            st.info("선택 Table 주변 ERD를 보려면 Focus Table을 선택하세요.")
            return
        max_hops = st.slider("관계 거리", 1, 3, 2, key="erd_hops")
    elif mode == "category":
        if not categories:
            st.info("등록된 Category가 없습니다. Category가 지정된 후 Category ERD를 사용할 수 있습니다.")
            return
        category_labels = [f"{item.get('name')} ({item.get('key')})" for item in categories]
        selected_category = st.selectbox("Category", category_labels, key="erd_category")
        category_id = int(categories[category_labels.index(selected_category)]["id"])

    visible_nodes, visible_edges, distances = filter_graph(
        nodes,
        edges,
        mode=mode,
        selected_id=selected_id,
        max_hops=max_hops,
        category_id=category_id,
        text_query=text_query,
    )

    v1, v2 = st.columns(2)
    v1.metric("Visible Tables", len(visible_nodes))
    v2.metric("Visible Relations", len(visible_edges))

    if not visible_nodes:
        st.info("조건에 맞는 Table이 없습니다.")
    else:
        payload = build_component_payload(
            visible_nodes,
            visible_edges,
            mode=mode,
            selected_id=selected_id,
            distances=distances,
            frame_height=780 if len(visible_nodes) > 12 else 680,
        )
        try:
            component = _erd_component()
            clicked = component(
                **payload,
                key=f"erd_flow_{source_id}_{mode}_{category_id or 'all'}",
                default=None,
            )
            if isinstance(clicked, dict) and clicked.get("table_id"):
                st.caption(
                    "그래프에서 선택: "
                    f"{clicked.get('table_key') or clicked.get('table_id')} "
                    "· Focus Table을 변경하면 주변 관계를 재탐색할 수 있습니다."
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"React ERD component 로드 실패: {exc}")

    st.markdown("### Relationship Details")
    rows = relation_rows(visible_edges)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("표시할 FK 관계가 없습니다.")

    with st.expander("ERD 기술 정보", expanded=False):
        st.json(
            {
                "renderer": "@xyflow/react + elkjs",
                "layout": "ELK layered / ORTHOGONAL",
                "source": graph.get("source"),
                "mode": mode,
                "selected_table_id": selected_id,
                "max_hops": max_hops,
                "category_id": category_id,
                "visible_table_ids": [int(node["id"]) for node in visible_nodes],
            }
        )
