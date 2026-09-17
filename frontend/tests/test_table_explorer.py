"""Unit tests for Table Explorer helper transformations."""

import unittest

from table_explorer import column_rows, filter_tables, index_rows, relation_rows


class TableExplorerHelpersTest(unittest.TestCase):
    def test_filter_tables_combines_category_schema_and_text(self) -> None:
        tables = [
            {
                "id": 1,
                "schema_name": "DEMIS_OWNER",
                "table_name": "TB_PT_MST",
                "table_comment": "환자 기본정보",
            },
            {
                "id": 2,
                "schema_name": "DEMIS_OWNER",
                "table_name": "TB_LAB_RST",
                "table_comment": "검사 결과",
            },
            {
                "id": 3,
                "schema_name": "OTHER",
                "table_name": "TB_PT_ARCHIVE",
                "table_comment": "환자 보관",
            },
        ]

        result = filter_tables(
            tables,
            schema_query="demis",
            text_query="환자",
            allowed_table_ids={1, 2},
        )

        self.assertEqual([row["id"] for row in result], [1])

    def test_filter_tables_searches_table_name_and_comment_case_insensitively(self) -> None:
        tables = [
            {"id": 1, "schema_name": "S", "table_name": "TB_LAB_RST", "table_comment": "검사 결과"},
            {"id": 2, "schema_name": "S", "table_name": "TB_PT_MST", "table_comment": "환자"},
        ]

        self.assertEqual([row["id"] for row in filter_tables(tables, text_query="lab")], [1])
        self.assertEqual([row["id"] for row in filter_tables(tables, text_query="검사")], [1])

    def test_detail_rows_are_human_readable(self) -> None:
        detail = {
            "columns": [
                {
                    "ordinal_position": 1,
                    "column_name": "PT_ID",
                    "data_type": "NUMBER",
                    "nullable": False,
                    "primary_key": True,
                    "unique": True,
                    "default_value": None,
                    "comment": "환자 식별자",
                }
            ],
            "indexes": [
                {
                    "index_name": "IX_PT_ID",
                    "is_unique": True,
                    "index_method": "BTREE",
                    "columns": ["PT_ID"],
                }
            ],
        }
        relations = [
            {
                "constraint": "FK_ENC_PT",
                "relation_type": "FOREIGN_KEY",
                "source_table": "TB_ENC_HIST",
                "target_table": "TB_PT_MST",
                "column_mapping": [{"source": "PT_ID", "target": "PT_ID"}],
            }
        ]

        self.assertEqual(column_rows(detail)[0]["Column"], "PT_ID")
        self.assertEqual(index_rows(detail)[0]["Columns"], "PT_ID")
        self.assertEqual(
            relation_rows(relations, direction="outbound")[0]["Related Table"],
            "TB_PT_MST",
        )
        self.assertEqual(
            relation_rows(relations, direction="inbound")[0]["Related Table"],
            "TB_ENC_HIST",
        )
        self.assertEqual(
            relation_rows(relations, direction="outbound")[0]["Column Mapping"],
            "PT_ID → PT_ID",
        )


if __name__ == "__main__":
    unittest.main()
