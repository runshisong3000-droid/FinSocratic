import json
import tempfile
import unittest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch,Mock
from finsocratic import forward_validation as f

class ForwardTests(unittest.TestCase):
    def test_future_outcomes_not_scored_and_duplicate_blocked(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'ROOT',Path(folder)):
            payload={'month':'2099-01','predictions':[{'fund_id':'x','neural':1,'ridge':2,'persistence':3}]}
            with f.connect() as c:c.execute('INSERT INTO cohorts VALUES (?,?)',('2099-01',json.dumps(payload)))
            store=Mock()
            result=f.evaluate(store)['cohorts'][0]
            self.assertEqual(result['state'],'awaiting_outcome')
            self.assertIsNone(result['mae'])
            store.nav_frame.assert_not_called()
            with self.assertRaises(Exception):
                with f.connect() as c:c.execute('INSERT INTO cohorts VALUES (?,?)',('2099-01','{}'))

    def test_mature_cohort_uses_paired_samples_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(f,'ROOT',Path(folder)):
            payload={'month':'2020-01','predictions':[
                {'fund_id':fid,'neural':1,'ridge':2,'persistence':3} for fid in ('complete','missing')]}
            with f.connect() as c:c.execute('INSERT INTO cohorts VALUES (?,?)',('2020-01',json.dumps(payload)))
            dates=pd.bdate_range('2019-12-31','2020-01-31')
            values=np.cumprod(1+np.resize([0.01,-0.005],len(dates)))
            nav=pd.DataFrame({'fund_id':'complete','date':dates,'nav':values})
            store=Mock();store.nav_frame.return_value=nav
            result=f.evaluate(store)['cohorts'][0]
            actual=nav.nav.pct_change().dropna().std()*np.sqrt(252)*100
            self.assertEqual(result['evaluated'],1)
            self.assertEqual(result['missing'],1)
            for key,prediction in [('neural',1),('ridge',2),('persistence',3)]:
                self.assertAlmostEqual(result['mae'][key],abs(prediction-actual))
