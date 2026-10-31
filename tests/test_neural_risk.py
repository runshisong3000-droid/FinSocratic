import unittest
import numpy as np
from finsocratic.neural_risk import RiskEnsemble

class Fixed:
    n_iter_=1
    loss_curve_=[1.]
    def predict(self,x): return np.ones(len(x))

class RiskTests(unittest.TestCase):
    def test_units_and_blend(self):
        m=RiskEnsemble([Fixed(),Fixed()],2,3,.5,0,10,2)
        np.testing.assert_allclose(m.predict(np.array([[1.,0.]])),[8.5])
    def test_nonnegative(self):
        m=RiskEnsemble([Fixed()],-10,1,1,0,0,1)
        self.assertEqual(m.predict(np.zeros((1,2)))[0],0)
