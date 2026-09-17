"""Offline ERD Explorer for DEMIS Schema Analyzer."""

from __future__ import annotations

from collections import deque
from html import escape
from typing import Any, Callable

import requests
import streamlit as st
import streamlit.components.v1 as components

ApiGet = Callable[..., requests.Response]


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


def _truncate(value: Any, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_svg_html(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    selected_id: int | None = None,
    distances: dict[int, int] | None = None,
) -> str:
    """Render deterministic, dependency-free SVG so the ERD works offline."""
    distances = distances or {}
    sorted_nodes = sorted(nodes, key=lambda n: (str(n.get("schema_name")), str(n.get("table_name"))))
    if not sorted_nodes:
        return "<div style='padding:24px'>표시할 Table이 없습니다.</div>"

    columns = 4 if len(sorted_nodes) > 9 else 3
    node_w, node_h = 260, 88
    gap_x, gap_y = 70, 70
    margin_x, margin_y = 55, 55
    rows = (len(sorted_nodes) + columns - 1) // columns
    width = max(980, margin_x * 2 + columns * node_w + (columns - 1) * gap_x)
    height = max(360, margin_y * 2 + rows * node_h + (rows - 1) * gap_y)

    positions: dict[int, tuple[float, float]] = {}
    for index, node in enumerate(sorted_nodes):
        row, col = divmod(index, columns)
        positions[int(node["id"])] = (
            margin_x + col * (node_w + gap_x),
            margin_y + row * (node_h + gap_y),
        )

    edge_parts: list[str] = []
    for edge in edges:
        source_id = int(edge["source_id"])
        target_id = int(edge["target_id"])
        if source_id not in positions or target_id not in positions:
            continue
        sx, sy = positions[source_id]
        tx, ty = positions[target_id]
        x1, y1 = sx + node_w / 2, sy + node_h / 2
        x2, y2 = tx + node_w / 2, ty + node_h / 2
        label = escape(str(edge.get("constraint") or "FK"))
        mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
        edge_parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            'stroke="#94a3b8" stroke-width="1.5" marker-end="url(#arrow)" />'
            f'<text x="{mid_x}" y="{mid_y - 5}" text-anchor="middle" '
            f'font-size="10" fill="#64748b">{label}</text>'
        )

    node_parts: list[str] = []
    for node in sorted_nodes:
        node_id = int(node["id"])
        x, y = positions[node_id]
        distance = distances.get(node_id)
        if selected_id is not None and node_id == int(selected_id):
            fill, stroke, opacity, stroke_w = "#dcfce7", "#16a34a", 1.0, 3
        elif distance == 1:
            fill, stroke, opacity, stroke_w = "#dbeafe", "#2563eb", 1.0, 2
        elif distance == 2:
            fill, stroke, opacity, stroke_w = "#f1f5f9", "#64748b", 1.0, 1.5
        elif selected_id is not None:
            fill, stroke, opacity, stroke_w = "#f8fafc", "#cbd5e1", 0.40, 1
        else:
            fill, stroke, opacity, stroke_w = "#ffffff", "#94a3b8", 1.0, 1.2
        title = escape(_truncate(node.get("table_name"), 28))
        schema = escape(_truncate(node.get("schema_name"), 28))
        comment = escape(_truncate(node.get("table_comment") or "DB COMMENT 없음", 35))
        categories = ", ".join(str(item.get("name")) for item in node.get("categories") or [])
        category_text = escape(_truncate(categories, 34))
        node_parts.append(
            f'<g opacity="{opacity}">'
            f'<rect x="{x}" y="{y}" width="{node_w}" height="{node_h}" rx="9" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_w}" />'
            f'<text x="{x + 14}" y="{y + 23}" font-size="11" fill="#64748b">{schema}</text>'
            f'<text x="{x + 14}" y="{y + 45}" font-size="15" font-weight="700" fill="#0f172a">{title}</text>'
            f'<text x="{x + 14}" y="{y + 64}" font-size="11" fill="#475569">{comment}</text>'
            + (
                f'<text x="{x + 14}" y="{y + 80}" font-size="10" fill="#7c3aed">{category_text}</text>'
                if category_text
                else ""
            )
            + "</g>"
        )

    return f"""
    <div style="font-family:Arial,sans-serif; overflow:auto; border:1px solid #e2e8f0; border-radius:10px; background:#fff;">
      <div style="padding:10px 14px; font-size:12px; color:#475569; border-bottom:1px solid #e2e8f0;">
        <span style="margin-right:18px">■ 선택 Table</span>
        <span style="margin-right:18px">■ 1-hop</span>
        <span style="margin-right:18px">■ 2-hop</span>
        <span>전체/기타 Table</span>
      </div>
      <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
        </defs>
        {''.join(edge_parts)}
        {''.join(node_parts)}
      </svg>
    </div>
    """


def _load_json(api_get: ApiGet, path: str, **kwargs: Any) -> Any:
    response = api_get(path, **kwargs)
    response.raise_for_status()
    return response.json()


def render_erd_explorer(*, targets: list[dict[str, Any]], api_get: ApiGet) -> None:
    st.title("ERD Explorer")
    st.caption("분석된 Catalog의 Table 관계를 전체·Category·선택 Table 주변 관점으로 탐색합니다.")

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

    html = render_svg_html(
        visible_nodes,
        visible_edges,
        selected_id=selected_id,
        distances=distances,
    )
    graph_height = min(900, max(460, 220 + ((len(visible_nodes) + 3) // 4) * 150))
    components.html(html, height=graph_height, scrolling=True)

    st.markdown("### Relationship Details")
    rows = relation_rows(visible_edges)
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("표시할 FK 관계가 없습니다.")

    with st.expander("ERD 기술 정보", expanded=False):
        st.json(
            {
                "source": graph.get("source"),
                "mode": mode,
                "selected_table_id": selected_id,
                "max_hops": max_hops,
                "category_id": category_id,
                "visible_table_ids": [int(node["id"]) for node in visible_nodes],
            }
        )
