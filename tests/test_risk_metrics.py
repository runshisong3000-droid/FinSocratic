"""Reference cases for tail-risk and drawdown deep-dive metrics."""
import unittest

import numpy as np
import pandas as pd

from finsocratic.data import fund_metrics
from finsocratic.risk_metrics import (
    conditional_var,
    historical_var,
    max_drawdown_duration,
    omega_ratio,
    tail_ratio,
)


class TailRiskTests(unittest.TestCase):
    def test_historical_var_matches_percentile(self):
        returns = pd.Series([0.01, -0.02, 0.03, -0.04, 0.05, -0.06])
        self.assertAlmostEqual(historical_var(returns, 0.95), np.percentile(returns, 5))

    def test_cvar_is_at_or_below_var(self):
        returns = pd.Series([0.01, -0.02, 0.03, -0.04, 0.05, -0.06, -0.01, 0.02])
        var = historical_var(returns, 0.95)
        cvar = conditional_var(returns, 0.95)
        self.assertLessEqual(cvar, var)

    def test_tail_ratio_symmetric_is_one(self):
        returns = pd.Series([0.01, -0.01, 0.02, -0.02])
        self.assertAlmostEqual(tail_ratio(returns), 1.0)

    def test_omega_gains_equal_losses_is_one(self):
        returns = pd.Series([0.03, -0.02, 0.01, -0.02])
        self.assertAlmostEqual(omega_ratio(returns), 1.0)

    def test_max_drawdown_duration_counts_longest_underwater_run(self):
        values = pd.Series([1.0, 0.9, 0.8, 0.85, 1.0, 0.7, 0.95])
        self.assertEqual(max_drawdown_duration(values), 3)

    def test_fund_metrics_exposes_tail_metrics(self):
        nav = pd.DataFrame({
            "fund_id": ["F"] * 6,
            "date": pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31", "2024-04-30", "2024-05-31", "2024-06-30"]),
            "nav": [1.0, 0.9, 0.8, 0.85, 1.0, 0.7],
        })
        metrics = fund_metrics(nav, "F")
        self.assertTrue(np.isfinite(metrics["var_95"]))
        self.assertTrue(np.isfinite(metrics["cvar_95"]))
        self.assertTrue(np.isfinite(metrics["tail_ratio"]))
        self.assertTrue(np.isfinite(metrics["omega_ratio"]))
        self.assertGreaterEqual(metrics["max_drawdown_duration"], 1)


if __name__ == "__main__":
    unittest.main()
