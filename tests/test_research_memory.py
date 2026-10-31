import unittest
from finsocratic.research_memory import compare, digest

class MemoryTests(unittest.TestCase):
    def test_key_order_is_not_new_evidence(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))

    def test_change_and_baseline(self):
        old={'净值':{'hash':'a','rows':2}}
        new={'净值':{'hash':'b','rows':3}}
        self.assertEqual(compare(None,new)['status'],'baseline')
        self.assertEqual(compare(old,old)['status'],'unchanged')
        self.assertEqual(compare(old,new)['changes'][0]['category'],'净值')
