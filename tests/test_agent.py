"""Independent, small reference cases for the offline diligence workflow."""
import json
import unittest

import pandas as pd

from finsocratic.agent import render_markdown, run_diligence


class DiligenceTests(unittest.TestCase):
    def setUp(self):
        self.fund = {"fund_id": "F-1", "name": "合成测试基金", "manager": "测试管理人", "strategy": "多策略"}
        self.nav = pd.DataFrame({
            "fund_id": ["F-1"] * 4,
            "date": ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"],
            "nav": [1.00, 1.10, 0.90, 0.95],
        })
        self.holdings = pd.DataFrame({
            "fund_id": ["F-1", "F-1"],
            "as_of": ["2025-04-30", "2025-04-30"],
            "asset": ["权益策略", "债券策略"],
            "weight_pct": [28.0, 72.0],
        })
        self.report = [{"name": "经理月报.txt", "chunks": [
            {"location": "第 2 页", "text": "最大回撤控制在5%以内。权益策略约占组合净值的28%。收益主要来自选股能力。"},
        ]}]

    def test_claims_have_source_and_independent_calculation_evidence(self):
        result = run_diligence(self.fund, self.nav, self.holdings, self.report)
        by_topic = {item["topic"]: item for item in result["claims"]}
        drawdown = by_topic["最大回撤"]
        self.assertEqual(drawdown["status"], "contradicted")
        self.assertAlmostEqual(result["metrics"]["max_drawdown"], 0.9 / 1.1 - 1)
        self.assertEqual(drawdown["location"], "第 2 页")
        self.assertIn("CALC-MAX_DRAWDOWN", drawdown["check_evidence_ids"])
        calc = next(e for e in result["evidence"] if e["id"] == "CALC-MAX_DRAWDOWN")
        self.assertEqual(len(calc["input_evidence_ids"]), 4)
        self.assertEqual(by_topic["组合配置：权益策略"]["status"], "supported_within_scope")
        self.assertEqual(by_topic["收益归因"]["status"], "unverifiable")
        self.assertTrue(any(q["priority"] == "高" for q in result["follow_up_questions"]))
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_retrieved_text_cannot_verify_a_qualitative_claim(self):
        documents = self.report + [{"name": "其他资料.txt", "chunks": [
            {"location": "第 1 行", "text": "收益主要来自选股能力。"},
        ]}]
        result = run_diligence(self.fund, self.nav, self.holdings, documents)
        qualitative = [item for item in result["claims"] if "选股能力" in item["text"]]
        self.assertTrue(qualitative)
        self.assertTrue(all(item["status"] == "unverifiable" for item in qualitative))
        self.assertTrue(all(not item["check_evidence_ids"] for item in qualitative))

    def test_conflicting_duplicate_and_invalid_values_are_reported(self):
        flawed = pd.concat([
            self.nav,
            pd.DataFrame({"fund_id": ["F-1", "F-1"], "date": ["2025-02-28", "2025-05-31"], "nav": [1.20, -2.0]}),
        ], ignore_index=True)
        result = run_diligence(self.fund, flawed, self.holdings, self.report)
        codes = {issue["code"] for issue in result["data_quality"]["issues"]}
        self.assertIn("nav_conflicting_dates", codes)
        self.assertIn("nav_invalid_rows", codes)
        self.assertEqual(result["data_quality"]["nav_observations"], 3)
        self.assertNotIn("2025-02-28", [e["location"] for e in result["evidence"] if e["source"] == "基金净值"])

    def test_benchmark_uses_exactly_matched_dates(self):
        benchmark = pd.DataFrame({
            "date": ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"],
            "nav": [1.00, 1.05, 1.12, 1.20],
        })
        docs = [{"name": "经理月报.txt", "chunks": [{"location": "第 3 页", "text": "本期跑赢基准。"}]}]
        result = run_diligence(self.fund, self.nav, self.holdings, docs, benchmark=benchmark)
        self.assertEqual(result["claims"][0]["status"], "contradicted")
        self.assertAlmostEqual(result["benchmark_comparison"]["relative_return_pp"], -25.0)
        shifted = benchmark.assign(date=["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"])
        no_match = run_diligence(self.fund, self.nav, self.holdings, docs, benchmark=shifted)
        self.assertEqual(no_match["claims"][0]["status"], "unverifiable")

    def test_percentage_lower_bound_is_not_treated_as_an_exact_value(self):
        docs = [{"name": "经理月报.txt", "chunks": [{"location": "第 1 页", "text": "本期区间收益至少为1%。"}]}]
        result = run_diligence(self.fund, self.nav, self.holdings, docs)
        self.assertEqual(result["claims"][0]["status"], "contradicted")
        improved = self.nav.copy()
        improved.loc[improved.index[-1], "nav"] = 1.15
        result = run_diligence(self.fund, improved, self.holdings, docs)
        self.assertEqual(result["claims"][0]["status"], "supported_within_scope")

    def test_negative_return_claim_preserves_its_sign(self):
        docs = [{"name": "经理月报.txt", "chunks": [{"location": "第 1 页", "text": "区间收益为−5%。"}]}]
        result = run_diligence(self.fund, self.nav, self.holdings, docs)
        self.assertAlmostEqual(result["metrics"]["total_return"], -0.05)
        self.assertEqual(result["claims"][0]["status"], "supported_within_scope")

    def test_monthly_drawdown_below_cap_does_not_verify_absolute_cap(self):
        calm = self.nav.copy()
        calm["nav"] = [1.00, 1.02, 1.00, 1.03]
        docs = [{"name": "经理月报.txt", "chunks": [{"location": "第 2 页", "text": "最大回撤控制在5%以内。"}]}]
        result = run_diligence(self.fund, calm, self.holdings, docs)
        claim = result["claims"][0]
        self.assertEqual(result["metrics"]["frequency"], "近似月频")
        self.assertEqual(claim["status"], "inconclusive")
        self.assertIn("当前采样频率不足", claim["explanation"])
        self.assertAlmostEqual(result["metrics"]["max_drawdown"], 1.00 / 1.02 - 1)
        self.assertIn("CALC-MAX_DRAWDOWN", claim["check_evidence_ids"])

    def test_prior_report_is_context_not_automatic_contradiction(self):
        previous = [{"name": "前期报告.txt", "chunks": [{"location": "第 4 段", "text": "最大回撤控制在3%以内。"}]}]
        result = run_diligence(self.fund, self.nav, self.holdings, self.report, prior_documents=previous)
        comparison = result["period_comparison"][0]
        self.assertEqual(comparison["change_type"], "numeric_shift")
        self.assertIn("报告期", comparison["assessment"])
        self.assertTrue(comparison["prior_source_evidence_id"].startswith("PRIOR-"))
        self.assertEqual(result["execution_mode"], "deterministic_offline")

    def test_markdown_export_contains_findings_and_locatable_sources(self):
        result = run_diligence(self.fund, self.nav, self.holdings, self.report)
        report = render_markdown(result)
        self.assertIn("与已导入数据矛盾", report)
        self.assertIn("第 2 页", report)
        self.assertIn("CALC-MAX_DRAWDOWN", report)
        self.assertIn("确定性离线检查", report)
        self.assertIn(result["manager_summary"], report)

    def test_row_locations_remain_original_after_fund_filter(self):
        other = pd.DataFrame({"fund_id": ["OTHER"], "date": ["2025-01-31"], "nav": [1.0]})
        nav = pd.concat([other, self.nav], ignore_index=True)
        result = run_diligence(self.fund, nav, self.holdings, self.report)
        first = next(item for item in result["evidence"] if item["source"] == "基金净值")
        self.assertIn("第 3 行", first["location"])

    def test_numeric_dates_are_parsed_only_when_unambiguous(self):
        numeric = self.nav.copy()
        numeric["date"] = [20250131, 20250228, 20250331, 20250430]
        result = run_diligence(self.fund, numeric, self.holdings, self.report)
        self.assertEqual(result["metrics"]["start"], "2025-01-31")
        numeric.loc[0, "date"] = 45700  # ambiguous Excel serial date
        result = run_diligence(self.fund, numeric, self.holdings, self.report)
        self.assertIn("nav_invalid_rows", {item["code"] for item in result["data_quality"]["issues"]})

    def test_numeric_evidence_names_original_files_with_per_row_fallback(self):
        nav = self.nav.copy()
        nav["source_file"] = [r"C:\imports\old_nav.csv", pd.NA, "new_nav.csv", ""]
        holdings = self.holdings.copy()
        holdings["source_file"] = ["positions_april.csv", pd.NA]
        benchmark = pd.DataFrame({"date": self.nav["date"], "nav": [1.0, 1.02, 1.03, 1.04]})
        result = run_diligence(
            self.fund, nav, holdings, self.report, benchmark=benchmark,
            source_labels={"nav": "fallback_nav.csv", "holdings": "fallback_holdings.csv", "benchmark": "benchmark.csv"},
        )
        sources = result["input_sources"]
        self.assertEqual(sources["nav"], ["fallback_nav.csv", "new_nav.csv", "old_nav.csv"])
        self.assertEqual(sources["holdings"], ["fallback_holdings.csv", "positions_april.csv"])
        self.assertEqual(sources["benchmark"], ["benchmark.csv"])
        self.assertEqual(result["data_quality"]["holdings_rows"], 2)
        report = render_markdown(result)
        for filename in ("old_nav.csv", "new_nav.csv", "fallback_nav.csv", "positions_april.csv", "benchmark.csv"):
            self.assertIn(filename, report)
        self.assertNotIn("C:\\imports", report)


if __name__ == "__main__":
    unittest.main()
