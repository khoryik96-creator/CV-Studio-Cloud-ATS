"""Budgeted evidence review for a claimed CV-scoring job.
Internal staging execution only: no automatic hiring decisions, ranking,
candidate recommendation, persistent results or public endpoints.
"""
from cloud.scoring_contract import prepare,validate,ScoringError
from cloud.ai_dispatch import BudgetedCompletion
from cloud.cv_engine import answer_json
from cloud.worker_leases import Lease

def execute(*,principal,lease,ledger,policy,transport,cv,jd,criteria,check):
    if not isinstance(lease,Lease) or lease.module!="cv_scoring" or not callable(check):
        raise ScoringError("scoring_lease_required")
    # Validate recruiter-selected rubric before requesting paid completion.
    system,user=prepare(cv,jd,criteria)
    check()
    completion=BudgetedCompletion(ledger,principal,lease,policy,transport)
    text=completion("assess",system,user,8192)
    check()
    result=validate(answer_json(text),cv,jd,criteria)
    check()
    return result
