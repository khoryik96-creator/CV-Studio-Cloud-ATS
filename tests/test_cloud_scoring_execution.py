import json
import unittest
from uuid import uuid4
from unittest.mock import Mock
from cloud.scoring_contract import Criterion,ScoringError
from cloud.scoring_execution import execute
from cloud.worker_leases import Lease
from cloud.ai_dispatch import ModelPolicy,Completion,DispatchError,BudgetedCompletion

class TestScoringExecution(unittest.TestCase):
    def setUp(self):
        self.lease=Lease(str(uuid4()),str(uuid4()),"cv_scoring",str(uuid4()))
        self.ledger=Mock()
        self.policy=ModelPolicy("deepseek","synthetic",100,200,16000,8192)
        self.cv="Fictional candidate built Python APIs."
        self.jd="Build Python APIs."
        self.criteria=[Criterion("python","Python APIs",True)]
        self.transport=Mock(return_value=Completion(json.dumps({"assessments":[{"id":"python","status":"evidenced","quote":"built Python APIs","note":"Relevant project evidence; verify scope."}]}),100,50))
        self.args=dict(principal=Mock(),lease=self.lease,ledger=self.ledger,policy=self.policy,transport=self.transport,cv=self.cv,jd=self.jd,criteria=self.criteria,check=Mock())
    def test_budgeted_evidence(self):
        result=execute(**self.args)
        self.assertTrue(result["human_review_required"])
        self.assertEqual(result["assessments"][0]["quote"],"built Python APIs")
        self.ledger.reserve.assert_called_once()
        self.ledger.settle.assert_called_once()
        self.transport.assert_called_once()
    def test_invalid_rubric_does_not_dispatch(self):
        with self.assertRaises(ScoringError):
            execute(**dict(self.args,criteria=[Criterion("fake","Not in JD",True)]))
        self.transport.assert_not_called()
        self.ledger.reserve.assert_not_called()
    def test_fabricated_evidence_is_rejected_after_billing(self):
        self.transport.return_value=Completion(json.dumps({"assessments":[{"id":"python","status":"evidenced","quote":"invented evidence","note":"Unsupported."}]}),100,50)
        with self.assertRaises(ScoringError):
            execute(**self.args)
        self.ledger.settle.assert_called_once()
    def test_module_stage_fence(self):
        c=BudgetedCompletion(self.ledger,self.args["principal"],self.lease,self.policy,self.transport)
        with self.assertRaises(DispatchError):
            c("parse","system","user",100)
        self.transport.assert_not_called()
