"""Unit tests for ERD Explorer graph helpers."""

from __future__ import annotations

import unittest

from erd_explorer import build_component_payload, filter_graph, hop_distances, relation_rows


NODES = [
    {"id": 1, "schema_name": "DEMIS_OWNER", "table_name": "TB_PT_MST", "table_comment": "환자", "categories": [{"id": 10, "name": "환자"}]},
    {"id": 2, "schema_name": "DEMIS_OWNER", "table_name": "TB_ENC_HIST", "table_comment": "진료", "categories": [{"id": 20, "name": "진료"}]},
    {"id": 3, "schema_name": "DEMIS_OWNER", "table_name": "TB_DX_HIST", "table_comment": "진단", "categories": [{"id": 20, "name": "진료"}]},
    {"id": 4, "schema_name": "DEMIS_OWNER", "table_name": "TB_LAB_RST", "table_comment": "검사", "categories": []},
]

EDGES = [
    {"id": 101, "constraint": "FK_ENC_PT", "source_id": 2, "target_id": 1, "source_table_key": "DEMIS_OWNER.TB_ENC_HIST", "target_table_key": "DEMIS_OWNER.TB_PT_MST", "column_mapping": [{"source": "PT_ID", "target": "PT_ID"}]},
    {"id": 102, "constraint": "FK_DX_ENC", "source_id": 3, "target_id": 2, "source_table_key": "DEMIS_OWNER.TB_DX_HIST", "target_table_key": "DEMIS_OWNER.TB_ENC_HIST", "column_mapping": [{"source": "ENC_ID", "target": "ENC_ID"}]},
]


class ErdExplorerHelpersTest(unittest.TestCase):
    def test_hop_distances_are_bounded(self) -> None:
        self.assertEqual(hop_distances(1, EDGES, max_hops=1), {1: 0, 2: 1})
        self.assertEqual(hop_distances(1, EDGES, max_hops=2), {1: 0, 2: 1, 3: 2})

    def test_neighborhood_filters_nodes_and_edges(self) -> None:
        nodes, edges, distances = filter_graph(
            NODES,
            EDGES,
            mode="neighborhood",
            selected_id=1,
            max_hops=1,
        )
        self.assertEqual([node["id"] for node in nodes], [1, 2])
        self.assertEqual([edge["id"] for edge in edges], [101])
        self.assertEqual(distances[2], 1)

    def test_category_and_text_filters(self) -> None:
        nodes, edges, _ = filter_graph(NODES, EDGES, mode="category", category_id=20)
        self.assertEqual([node["id"] for node in nodes], [2, 3])
        self.assertEqual([edge["id"] for edge in edges], [102])

        nodes, _, _ = filter_graph(NODES, EDGES, mode="full", text_query="lab")
        self.assertEqual([node["id"] for node in nodes], [4])

    def test_relation_rows_and_component_contract(self) -> None:
        rows = relation_rows(EDGES)
        self.assertEqual(rows[0]["Mapping"], "PT_ID → PT_ID")

        full = build_component_payload(
            NODES[:3],
            EDGES,
            mode="full",
            selected_id=1,
            distances={1: 0, 2: 1, 3: 2},
        )
        self.assertEqual(full["selectedId"], 1)
        self.assertEqual(full["distances"], {"1": 0, "2": 1, "3": 2})
        self.assertFalse(full["showEdgeLabels"])
        self.assertEqual(len(full["nodes"]), 3)

        neighborhood = build_component_payload(
            NODES[:3],
            EDGES,
            mode="neighborhood",
            selected_id=1,
            distances={1: 0, 2: 1, 3: 2},
        )
        self.assertTrue(neighborhood["showEdgeLabels"])


if __name__ == "__main__":
    unittest.main()
