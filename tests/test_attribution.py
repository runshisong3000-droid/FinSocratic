"""Deterministic reference cases for risk-adjusted attribution and downside metrics."""
import math
import unittest

import numpy as np
import pandas as pd

from finsocratic.agent import run_diligence
from finsocratic.attribution import risk_adjusted_attribution, rolling_beta
from finsocratic.data import fund_metrics


def _series(*values):
    return pd.Series(list(values), dtype=float)


class AttributionTests(unittest.TestCase):
    def test_identical_series_have_unit_beta_and_zero_tracking_error(self):
        returns = _series(0.01, -0.02, 0.03, 0.01, 0.005)
        result = risk_adjusted_attribution(returns, returns, periods_per_year=12)
        metrics = result["metrics"]
        self.assertAlmostEqual(metrics["beta"], 1.0)
        self.assertAlmostEqual(metrics["correlation"], 1.0)
        self.assertAlmostEqual(metrics["r_squared"], 1.0)
        self.assertAlmostEqual(metrics["tracking_error"], 0.0)
        self.assertAlmostEqual(metrics["alpha_annualized"], 0.0, places=10)
        self.assertAlmostEqual(metrics["active_return_annualized"], 0.0, places=10)
        self.assertIsNone(metrics["information_ratio"])

    def test_attribution_returns_none_when_periods_missing(self):
        returns = _series(0.01, -0.02, 0.03)
        result = risk_adjusted_attribution(returns, returns, periods_per_year=None)
        self.assertIsNone(result["metrics"]["tracking_error"])
        self.assertEqual(result["observations"], 3)

    def test_capture_ratios_match_hand_computation(self):
        fund = _series(0.02, -0.01, 0.03, -0.02)
        benchmark = _series(0.01, 0.01, -0.01, -0.01)
        result = risk_adjusted_attribution(fund, benchmark, periods_per_year=12)
        up = benchmark > 0
        down = benchmark < 0
        self.assertAlmostEqual(result["metrics"]["up_capture_ratio"], fund[up].sum() / benchmark[up].sum())
        self.assertAlmostEqual(result["metrics"]["down_capture_ratio"], fund[down].sum() / benchmark[down].sum())

    def test_rolling_beta_uses_trailing_window(self):
        fund = _series(0.01, 0.02, 0.01, 0.02)
        benchmark = _series(0.01, 0.02, 0.01, 0.02)
        dates = pd.Series(pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]))
        rows = rolling_beta(fund, benchmark, dates, window=2)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["end_date"], "2024-04-30")
        self.assertAlmostEqual(rows[0]["beta"], 1.0)

    def test_benchmark_run_exposes_attribution(self):
        fund = {"fund_id": "F-1", "name": "合成测试基金", "manager": "测试管理人", "strategy": "多策略"}
        nav = pd.DataFrame({
            "fund_id": ["F-1"] * 4,
            "date": ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"],
            "nav": [1.00, 1.10, 0.90, 0.95],
        })
        benchmark = pd.DataFrame({
            "date": ["2025-01-31", "2025-02-28", "2025-03-31", "2025-04-30"],
            "nav": [1.00, 1.05, 1.12, 1.20],
        })
        result = run_diligence(fund, nav, pd.DataFrame(), [{"name": "r.txt", "chunks": [{"location": "第 1 行", "text": "本期跑赢基准。"}]}], benchmark=benchmark)
        attribution = result["benchmark_comparison"]["attribution"]
        self.assertIsNotNone(attribution)
        self.assertIn("beta", attribution)
        self.assertIn("CALC-ATTR-BETA", {item["id"] for item in result["evidence"]})


class DownsideMetricTests(unittest.TestCase):
    def test_sortino_and_calmar_are_computed(self):
        nav = pd.DataFrame({
            "fund_id": ["F"] * 5,
            "date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31"]),
            "nav": [1.0, 1.10, 0.95, 1.05, 1.00],
        })
        metrics = fund_metrics(nav, "F")
        self.assertTrue(math.isfinite(metrics["sortino"]))
        self.assertTrue(math.isfinite(metrics["calmar"]))
        self.assertAlmostEqual(metrics["calmar"], metrics["annual_return"] / abs(metrics["max_drawdown"]))

    def test_sortino_withheld_when_no_downside(self):
        nav = pd.DataFrame({
            "fund_id": ["F"] * 4,
            "date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30"]),
            "nav": [1.0, 1.02, 1.04, 1.06],
        })
        metrics = fund_metrics(nav, "F")
        self.assertTrue(pd.isna(metrics["sortino"]))
        self.assertEqual(metrics["downside_deviation"], 0.0)


if __name__ == "__main__":
    unittest.main()
