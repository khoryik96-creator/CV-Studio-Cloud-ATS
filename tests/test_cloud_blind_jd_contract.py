import unittest
from cloud.blind_jd_contract import validate,BlindJDError,FIELDS,LISTS

class TestBlindJD(unittest.TestCase):
    def setUp(self):
        self.source="ExampleCo requires Python and Linux."
        self.report={k:"" for k in FIELDS}
        self.report.update({k:[] for k in LISTS})
        self.report.update(job_title="Engineer",tech_stack=["Python","Linux"],responsibilities=["Build services"],requirements=["Python experience"])
    def check(self):
        return validate(self.report,self.source,identifiers=["ExampleCo"],technologies=["Python","Linux"])
    def test_review(self):
        self.assertTrue(self.check()["human_review_required"])
    def test_employer_leak(self):
        self.report["about_client"]="Join EXAMPLECO"
        with self.assertRaises(BlindJDError):
            self.check()
    def test_missing_technology(self):
        self.report["tech_stack"]=["Python"]
        with self.assertRaises(BlindJDError):
            self.check()
    def test_contact_leak(self):
        self.report["why_join"]=["Contact recruiter@example.invalid"]
        with self.assertRaises(BlindJDError):
            self.check()
