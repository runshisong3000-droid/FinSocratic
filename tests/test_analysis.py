import unittest

import numpy as np
import pandas as pd

from finsocratic.analysis import assess_claims, fund_research_report, portfolio_metrics, screen_funds
from finsocratic.data import fund_metrics, load_samples, normalize_nav


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.funds, cls.nav, cls.holdings = load_samples()

    def test_sample_portfolio_weights_add_to_one_hundred(self):
        metrics = portfolio_metrics(self.holdings, "FOF-001")
        self.assertTrue(metrics["available"])
        self.assertAlmostEqual(metrics["reported_weight_sum"], 100.0)
        self.assertEqual(metrics["asset_count"], 5)

    def test_claim_check_reports_metric_and_limit(self):
        fund = self.funds.iloc[0]
        results = assess_claims("权益策略约占组合净值的28%。最大回撤控制在5%以内。", fund, self.nav, self.holdings)
        self.assertEqual(len(results), 2)
        self.assertIn(results[0]["判断"], {"与快照相符", "与快照不符"})
        self.assertIn("月频", results[1]["证据与限制"])

    def test_unmapped_claim_is_not_assumed_true(self):
        fund = self.funds.iloc[0]
        results = assess_claims("策略能够持续战胜市场。", fund, self.nav, self.holdings)
        self.assertEqual(results[0]["判断"], "当前数据无法检验")

    def test_screen_ranks_only_sufficient_history_and_is_transparent(self):
        result = screen_funds(self.funds, self.nav, self.holdings, min_observations=12, max_drawdown_limit=0.8)
        self.assertEqual(int(result["可排名"].sum()), 3)
        self.assertEqual(result.loc[result["可排名"], "名次"].tolist(), [1, 2, 3])
        self.assertTrue(result.loc[result["可排名"], "筛选分数"].between(0, 1).all())

    def test_screen_excludes_short_history(self):
        result = screen_funds(self.funds, self.nav, self.holdings, min_observations=60)
        self.assertFalse(result["可排名"].any())
        self.assertTrue(result["未入选原因"].str.contains("观测不足").all())

    def test_metrics_match_fund_ids_across_string_and_integer_inputs(self):
        nav = pd.DataFrame({"fund_id": [7, 7], "date": pd.to_datetime(["2024-01-01", "2025-01-01"]), "nav": [1.0, 1.1]})
        metrics = fund_metrics(nav, "7")
        self.assertEqual(metrics["months"], 2)
        self.assertAlmostEqual(metrics["total_return"], 0.1)

    def test_annual_return_uses_elapsed_dates(self):
        nav = pd.DataFrame({"fund_id": ["F", "F"], "date": pd.to_datetime(["2024-01-01", "2025-01-01"]), "nav": [1.0, 1.1]})
        metrics = fund_metrics(nav, "F")
        self.assertAlmostEqual(metrics["annual_return"], 0.1, places=3)

    def test_daily_risk_uses_daily_periods(self):
        nav = pd.DataFrame({"fund_id": ["F"] * 5, "date": pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]), "nav": [1.0, 1.01, 1.00, 1.02, 1.015]})
        metrics = fund_metrics(nav, "F")
        expected = nav["nav"].pct_change().dropna().std(ddof=1) * np.sqrt(252)
        self.assertEqual(metrics["frequency"], "日频")
        self.assertAlmostEqual(metrics["volatility"], expected)

    def test_irregular_risk_is_withheld(self):
        nav = pd.DataFrame({"fund_id": ["F"] * 4, "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-03-01", "2024-03-02"]), "nav": [1.0, 1.01, 1.03, 1.02]})
        metrics = fund_metrics(nav, "F")
        self.assertEqual(metrics["frequency"], "不规则")
        self.assertTrue(pd.isna(metrics["volatility"]))
        self.assertTrue(pd.isna(metrics["sharpe"]))

    def test_portfolio_uses_only_latest_snapshot(self):
        old = self.holdings.loc[self.holdings.fund_id == "FOF-001"].copy()
        old["as_of"] = pd.Timestamp("2024-12-31")
        old["weight_pct"] = old["weight_pct"] / 2
        combined = pd.concat([old, self.holdings], ignore_index=True)
        metrics = portfolio_metrics(combined, "FOF-001")
        self.assertEqual(metrics["asset_count"], 5)
        self.assertAlmostEqual(metrics["reported_weight_sum"], 100)
        self.assertEqual(metrics["as_of"], "2025-12-31")
        self.assertIn("权益策略", fund_research_report(self.funds.iloc[0], self.nav, combined))

    def test_invalid_snapshot_weights_are_rejected(self):
        bad = self.holdings.copy()
        bad.loc[bad.fund_id == "FOF-001", "weight_pct"] = -1
        result = portfolio_metrics(bad, "FOF-001")
        self.assertFalse(result["available"])
        self.assertIn("无效权重", result["reason"])

    def test_claim_aggregates_duplicate_asset_rows_in_latest_snapshot(self):
        holdings = self.holdings.copy()
        equity = holdings.loc[(holdings.fund_id == "FOF-001") & (holdings.asset == "权益策略")].iloc[0].copy()
        holdings.loc[(holdings.fund_id == "FOF-001") & (holdings.asset == "权益策略"), "weight_pct"] = 20
        equity["weight_pct"] = 8
        holdings = pd.concat([holdings, equity.to_frame().T], ignore_index=True)
        result = assess_claims("权益策略约占组合净值的28%。", self.funds.iloc[0], self.nav, holdings)
        self.assertEqual(result[0]["判断"], "与快照相符")

    def test_empty_workspace_and_nonfinite_nav_are_safe(self):
        empty = screen_funds(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        self.assertTrue(empty.empty)
        nav, warnings = normalize_nav(pd.DataFrame({"日期": ["2024-01-01", "2024-02-01"], "净值": [1.0, float("inf")]}), "日期", "净值", "7")
        self.assertEqual(len(nav), 1)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
