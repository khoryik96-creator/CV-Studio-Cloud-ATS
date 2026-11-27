import unittest
from uuid import uuid4
from cloud.ai_dispatch import BudgetedCompletion,ModelPolicy,Completion,DispatchError
from cloud.ai_budget import BudgetDenied
from cloud.worker_leases import Lease

class Ledger:
    def __init__(self):
        self.holds={}
        self.settled={}
    def reserve(self,p,l,**kwargs):
        key=kwargs["operation_id"]
        if key in self.holds:
            raise BudgetDenied("duplicate")
        self.holds[key]=kwargs["estimated_microusd"]
    def settle(self,p,l,**kwargs):
        self.settled[kwargs["operation_id"]]=kwargs["actual_microusd"]

class TestDispatch(unittest.TestCase):
    def setup_dispatch(self,transport):
        ledger=Ledger()
        lease=Lease(str(uuid4()),str(uuid4()),"cv_formatting",str(uuid4()))
        policy=ModelPolicy("deepseek","synthetic-model",1_000_000,2_000_000,1000,100)
        return ledger,BudgetedCompletion(ledger,None,lease,policy,transport)
    def test_budget_before_call_and_no_duplicate(self):
        calls=[]
        ledger,dispatch=self.setup_dispatch(lambda *args:(calls.append(len(ledger.holds)) or Completion("answer",10,5)))
        self.assertEqual(dispatch("parse","system","user",50),"answer")
        self.assertEqual(calls,[1])
        self.assertEqual(list(ledger.holds.values()),[1100])
        self.assertEqual(list(ledger.settled.values()),[20])
        with self.assertRaises(BudgetDenied):
            dispatch("parse","system","user",50)
        self.assertEqual(calls,[1])
    def test_uncertain_charge_remains_reserved(self):
        def fail(*args):
            raise RuntimeError("fictional sensitive provider text")
        ledger,dispatch=self.setup_dispatch(fail)
        with self.assertRaisesRegex(DispatchError,"provider_outcome_requires_review"):
            dispatch("parse","system","user",50)
        self.assertEqual(len(ledger.holds),1)
        self.assertFalse(ledger.settled)
