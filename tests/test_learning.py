"""Small checks for statistical invariants and absence of future-feature leakage."""
import unittest
import numpy as np
import pandas as pd
from finsocratic.learning import posterior, features, family


class LearningChecks(unittest.TestCase):
    def test_prior_and_sequential_evidence(self):
        self.assertAlmostEqual(posterior([])['probability_positive_mean'], .5)
        weak = posterior([.01]*12, 1)
        strong = posterior([.01]*12, 12)
        self.assertGreater(weak['mean_quarterly_excess'], strong['mean_quarterly_excess'])
        self.assertGreater(weak['probability_positive_mean'], .5)
        self.assertLess(posterior([-.01]*12)['probability_positive_mean'], .5)

    def test_features_do_not_read_future(self):
        dates = pd.bdate_range('2020-01-01', periods=350)
        nav = pd.DataFrame({'date': dates, 'nav': np.exp(np.cumsum(np.random.default_rng(42).normal(0,.01,350)))})
        before = features(nav)
        modified = nav.copy()
        modified.loc[modified.date >= '2020-11-01', 'nav'] *= 3
        after = features(modified)
        from finsocratic.learning import FEATURES
        a = before[before.date < '2020-11-01'].set_index('date')[FEATURES]
        b = after[after.date < '2020-11-01'].set_index('date')[FEATURES]
        pd.testing.assert_frame_equal(a,b)
        self.assertTrue((before.target_date > before.date).all())

    def test_share_class_group(self):
        self.assertEqual(family('示例FOF基金A'),family('示例FOF基金C'))


if __name__ == '__main__':
    unittest.main()
