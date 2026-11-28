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


    def test_technology_must_match_source_term(self):
        from cloud.blind_jd_contract import prepare
        for source,term in (("CPython only","Python"),("C++ only","C")):
            with self.subTest(source=source):
                with self.assertRaisesRegex(BlindJDError,"technology_not_in_source"):
                    prepare(source,identifiers=[],technologies=[term])

    def test_multiword_technology_cannot_span_entries(self):
        self.report["tech_stack"]=["SQL","Server"]
        with self.assertRaisesRegex(BlindJDError,"missing_required_technology"):
            validate(self.report,"SQL Server experience",identifiers=[],technologies=["SQL Server"])

    def test_invisible_characters_in_employer(self):
        self.report["about_client"]="Join Exam\u200bpleCo"
        with self.assertRaisesRegex(BlindJDError,"possible_employer_leak"):
            self.check()

    def test_invisible_only_identifier_rejected(self):
        from cloud.blind_jd_contract import prepare
        with self.assertRaisesRegex(BlindJDError,"invalid_terms"):
            prepare(self.source,identifiers=["\u200b"],technologies=[])

    def test_normalized_technology_match(self):
        self.report["tech_stack"]=["Ｐｙｔｈｏｎ","Linux"]
        self.assertTrue(self.check()["human_review_required"])
