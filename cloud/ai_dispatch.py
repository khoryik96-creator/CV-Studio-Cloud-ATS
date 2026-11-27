"""Budgeted completion boundary; provider transport is deliberately injected.

Configured prices and token ceilings are trusted server policy, never supplied
by the user. This boundary makes at most one call for a stable job/stage ID.
No retry or automatic release on exceptions/unknown usage.
"""
from dataclasses import dataclass
from uuid import UUID, uuid5
from cloud.ai_budget import model_id, amount, BudgetDenied

class DispatchError(ValueError):
    pass

@dataclass(frozen=True)
class ModelPolicy:
    provider: str
    model: str
    # Integer micro-USD per million tokens.
    input_rate: int
    output_rate: int
    max_input_tokens: int
    max_output_tokens: int

@dataclass(frozen=True, repr=False)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int

def _tokens(value):
    if type(value) is not int or not 0<=value<=10_000_000:
        raise DispatchError("invalid_provider_usage")
    return value

def _cost(p, input_tokens, output_tokens):
    return (input_tokens*p.input_rate+output_tokens*p.output_rate+999_999)//1_000_000

class BudgetedCompletion:
    def __init__(self, ledger, principal, lease, policy, transport):
        model_id(policy.provider,policy.model)
        amount(policy.input_rate,allow_zero=True)
        amount(policy.output_rate,allow_zero=True)
        if not 1<=_tokens(policy.max_input_tokens) or not 1<=_tokens(policy.max_output_tokens):
            raise DispatchError("invalid_model_limits")
        if policy.input_rate==0 and policy.output_rate==0:
            raise DispatchError("missing_model_price")
        self.ledger,self.principal,self.lease=ledger,principal,lease
        self.policy,self.transport=policy,transport

    def __call__(self,stage,system,user,max_tokens):
        if stage not in ("parse","blind") or not isinstance(system,str) or not isinstance(user,str):
            raise DispatchError("invalid_completion_request")
        p=self.policy
        # Reserve full configured input ceiling (not a guessed tokenizer count)
        # and the requested output cap. Transport must enforce the model's real
        # context limit and disable retries; usage may still exceed estimates.
        limit=min(_tokens(max_tokens),p.max_output_tokens)
        if limit<1 or len(system.encode("utf-8"))+len(user.encode("utf-8"))>p.max_input_tokens:
            raise DispatchError("completion_input_limit")
        operation=str(uuid5(UUID(self.lease.job_id),"cvcloud:"+stage))
        self.ledger.reserve(self.principal,self.lease,operation_id=operation,
            provider=p.provider,model=p.model,estimated_microusd=max(1,_cost(p,p.max_input_tokens,limit)))
        try:
            result=self.transport(p.provider,p.model,system,user,limit)
            if not isinstance(result,Completion):
                raise DispatchError("unknown_provider_usage")
            actual=_cost(p,_tokens(result.input_tokens),_tokens(result.output_tokens))
        except Exception:
            # No provider response text, credentials or source content in errors.
            raise DispatchError("provider_outcome_requires_review") from None
        self.ledger.settle(self.principal,self.lease,operation_id=operation,actual_microusd=actual)
        if result.input_tokens>p.max_input_tokens or result.output_tokens>limit:
            raise DispatchError("provider_usage_exceeded_limits")
        if not isinstance(result.text,str):
            raise DispatchError("invalid_provider_response")
        return result.text
