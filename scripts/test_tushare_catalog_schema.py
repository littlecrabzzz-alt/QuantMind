"""Field schema tables must not absorb later category or formula examples."""

from html import escape
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.shared.tushare_intake import parse_document


def table(rows):
    return (
        "<table>"
        + "".join(
            "<tr>" + "".join("<td>" + escape(v) + "</td>" for v in row) + "</tr>"
            for row in rows
        )
        + "</table>"
    )


class CatalogSchema(unittest.TestCase):
    def setUp(self):
        self.evidence = json.loads(
            (ROOT / "docs/tushare-factor-catalog-schema.evidence.json").read_text()
        )
        guard = patch(
            "socket.socket.connect", side_effect=AssertionError("offline schema test")
        )
        guard.start()
        self.addCleanup(guard.stop)

    def test_actual_factor_schema_excludes_category_and_numbered_formula_tables(self):
        evidence = self.evidence
        html = '<div class="col-md-9"><p>接口：factor_list</p><p>输出参数</p>'
        html += table(evidence["schema_table"]["rows"])
        html += table(
            [evidence["ignored_table_headers"][0]]
            + [
                [name, "说明", "31", "示例"]
                for name in evidence["ignored_category_names"]
            ]
        )
        html += table(
            [evidence["ignored_table_headers"][1]]
            + [
                [number, "example_factor", "source description"]
                for number in evidence["ignored_formula_row_first_cells"]
            ]
        )
        result = parse_document(html + "</div>", 486, "因子列表")
        self.assertEqual(result["output_fields"], evidence["after"]["output_fields"])
        self.assertEqual(result["api_names"], ["factor_list"])
        self.assertEqual(result["audit_status"], "schema_extracted")
        self.assertEqual(result["permission_status"], "unprobed")

    def test_compact_tables_hidden_and_digit_leading_fields_are_retained(self):
        html = '<div class="col-md-9"><p>接口：example</p><p>输入参数</p>'
        html += table([["名称"], ["trade_date"]])
        html += "<p>输出字段</p>" + table(
            [
                ["名称", "默认显示"],
                ["1w", "Y"],
                ["3day", "N"],
                ["3day", "N"],
                ["1year", "Y"],
                ["bad;field", "Y"],
            ]
        )
        html += table(
            [["名称", "类型", "默认显示", "描述"], ["2m", "float", "Y", "期限"]]
        )
        result = parse_document(html + "</div>", 1, "示例")
        self.assertEqual(result["input_fields"], ["trade_date"])
        self.assertEqual(result["output_fields"], ["1w", "3day", "1year", "2m"])

    def test_explanatory_or_empty_tables_do_not_fake_a_schema(self):
        html = '<div class="col-md-9"><p>接口：example</p><p>输入参数</p>'
        html += table([["分类名", "说明"], ["STK", "stock"]])
        html += "<p>输出参数</p>" + table([]) + table([[]])
        html += table([["序号", "因子名称", "算法逻辑"], ["1", "alpha", "formula"]])
        result = parse_document(html + "</div>", 1, "示例")
        self.assertEqual(result["input_fields"], [])
        self.assertEqual(result["output_fields"], [])
        self.assertEqual(result["audit_status"], "manual_review_required")

    def test_input_code_reference_tables_are_not_parameters(self):
        html = '<div class="col-md-9"><p>接口：example</p><p>输入参数</p>'
        html += table(
            [["名称", "类型", "必选", "描述"], ["ts_code", "str", "N", "代码"]]
        )
        html += table(
            [
                ["板块代码（TS_CODE）", "板块说明", "数据开始日期"],
                ["ETF", "基金", "20000101"],
            ]
        )
        html += table([["TS指数代码", "指数名称"], ["SPX", "指数"]])
        result = parse_document(html + "</div>", 1, "示例")
        self.assertEqual(result["input_fields"], ["ts_code"])

    def test_named_example_table_is_not_a_field_schema(self):
        html = '<div class="col-md-9"><p>接口：hm_list</p><p>输出参数</p>'
        html += table(
            [["名称", "类型", "默认显示", "描述"], ["name", "str", "Y", "名称"]]
        )
        html += table(
            [["名称", "说明", "关联机构"], ["Asking", "示例名称", "示例机构"]]
        )
        result = parse_document(html + "</div>", 311, "游资名录")
        self.assertEqual(result["output_fields"], ["name"])

    def test_catalog_target_sha_and_exact_nine_field_difference(self):
        catalog = json.loads((ROOT / "config/tushare-catalog.json").read_text())
        evidence = self.evidence
        self.assertEqual(len(catalog["entries"]), evidence["baseline_entries"])
        entry = next(e for e in catalog["entries"] if e["doc_id"] == "486")
        self.assertEqual(entry, evidence["after"])
        before = dict(evidence["before"])
        before["output_fields"] = entry["output_fields"]
        self.assertEqual(before, entry)
        self.assertEqual(entry["html_sha256"], evidence["source_html_sha256"])
        self.assertEqual(
            set(evidence["removed_output_fields"]),
            {
                "Alpha101",
                "Growth",
                "Liquidity",
                "Momentum",
                "Quality",
                "Reversal",
                "Risk",
                "Size",
                "Value",
            },
        )
        self.assertEqual(evidence["added_output_fields"], [])
        self.assertEqual(
            entry["output_fields"],
            ["factor_name", "asset_type", "factor_type", "factor_desc"],
        )


if __name__ == "__main__":
    unittest.main()
