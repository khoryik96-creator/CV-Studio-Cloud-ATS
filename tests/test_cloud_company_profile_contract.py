import copy
import unittest
from cloud.company_profile_contract import Source,prepare,validate,ProfileError

class TestProfileContract(unittest.TestCase):
    def setUp(self):
        self.sources=[Source("a","Fictional annual report","ExampleCo builds payment software. It employed 120 people in 2024.","https://example.invalid/report","2025-02-01")]
        self.report={"claims":[{"section":"business","text":"Builds payment software.","evidence":[{"source_id":"a","quote":"ExampleCo builds payment software."}]}],"limitations":["No recent staffing data."]}
    def check(self):
        return validate(self.report,"ExampleCo",self.sources)
    def test_grounded_claim(self):
        result=self.check()
        self.assertTrue(result["human_review_required"])
        self.assertEqual(result["source_verification"],"supplied_excerpts_only")
        self.assertEqual(result["sources"][0]["retrieved_on"],"2025-02-01")
    def test_reject_missing_or_invented_citation(self):
        for item in ({"source_id":"other","quote":"ExampleCo builds payment software."},{"source_id":"a","quote":"Has 500 employees."}):
            self.report["claims"][0]["evidence"]=[item]
            with self.assertRaises(ProfileError):
                self.check()
    def test_options_and_sources(self):
        system,user=prepare("ExampleCo",self.sources,focus="tech",length="detailed")
        self.assertIn("untrusted data",system)
        self.assertIn("ExampleCo builds payment software",user)
        for sources in ([Source("a","Title","Text","javascript:alert(1)")],[Source("a","Title","Text",retrieved_on="2025-02-31")],self.sources*2):
            with self.assertRaises(ProfileError):
                prepare("ExampleCo",sources)
    def test_empty_and_duplicate_claims(self):
        self.report["claims"].append(copy.deepcopy(self.report["claims"][0]))
        with self.assertRaises(ProfileError):
            self.check()
        self.report["claims"]=[]
        with self.assertRaises(ProfileError):
            self.check()
