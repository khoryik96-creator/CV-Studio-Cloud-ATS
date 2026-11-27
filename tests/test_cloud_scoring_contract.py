import unittest
from cloud.scoring_contract import Criterion,prepare,validate,ScoringError

class TestScoringContract(unittest.TestCase):
    def setUp(self):
        self.cv="Built Python services."
        self.jd="Python development"
        self.rubric=[Criterion("python",self.jd,True)]
        self.report={"assessments":[{"id":"python","status":"evidenced","quote":"Built Python services.","note":"Relevant experience"}]}
    def test_evidence(self):
        self.assertTrue(validate(self.report,self.cv,self.jd,self.rubric)["human_review_required"])
    def test_hallucinated_evidence(self):
        self.report["assessments"][0]["quote"]="Built Go services."
        with self.assertRaises(ScoringError):
            validate(self.report,self.cv,self.jd,self.rubric)
    def test_unrelated_criterion(self):
        with self.assertRaises(ScoringError):
            prepare(self.cv,self.jd,[Criterion("go","Go experience",True)])
    def test_missing_criterion(self):
        self.report["assessments"]=[]
        with self.assertRaises(ScoringError):
            validate(self.report,self.cv,self.jd,self.rubric)
