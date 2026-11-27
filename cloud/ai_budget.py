"""Fail-closed, tenant-wide prepaid reservation ledger.

Internal worker code only. No network calls, no user-supplied prices and no
automatic retry of uncertain provider requests. A reservation is a one-shot
authorization, not an idempotent permit to submit a second paid call.
"""
from dataclasses import dataclass
from cloud.documents_jobs import uid
from cloud.worker_leases import Lease
import re

PROVIDERS = frozenset({"deepseek", "anthropic", "openai", "google"})
MAX_MICROUSD = 1_000_000_000_000
MODEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}")

class BudgetDenied(ValueError):
    pass

@dataclass(frozen=True)
class Reservation:
    operation_id: str
    amount_microusd: int

def amount(value, *, allow_zero=False):
    if type(value) is not int or not (0 if allow_zero else 1) <= value <= MAX_MICROUSD:
        raise ValueError("Invalid cost amount")
    return value

def model_id(provider, model):
    if not isinstance(provider, str) or provider not in PROVIDERS or not isinstance(model, str) or not MODEL.fullmatch(model) or "://" in model:
        raise ValueError("Invalid provider or model")
    return provider, model

class AIBudget:
    def __init__(self, repository):
        self.repository = repository

    @staticmethod
    def _check_lease(conn, tenant, owner, lease):
        if not isinstance(lease, Lease):
            raise BudgetDenied("Worker lease required")
        row = conn.execute("""SELECT j.id FROM cvcloud.jobs j
            JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
            JOIN cvcloud.tenants t ON t.id=j.tenant_id
            WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s
            AND j.state='running' AND j.lease_token=%s AND j.lease_until>clock_timestamp()
            AND u.active AND t.active FOR UPDATE OF j""",
            (tenant,owner,uid(lease.job_id),uid(lease.token))).fetchone()
        if not row:
            raise BudgetDenied("Worker lease is no longer valid")

    def reserve(self, principal, lease, *, operation_id, provider, model, estimated_microusd):
        """Only the first committed call permits dispatch; duplicate IDs fail closed."""
        operation_id=uid(operation_id)
        provider,model=model_id(provider,model)
        estimate=amount(estimated_microusd)
        with self.repository.scoped(principal) as (conn,tenant,owner):
            budget=conn.execute("""SELECT limit_microusd,reserved_microusd,spent_microusd
                FROM cvcloud.ai_budgets WHERE tenant_id=%s FOR UPDATE""",(tenant,)).fetchone()
            if not budget:
                raise BudgetDenied("No budget configured")
            self._check_lease(conn,tenant,owner,lease)
            if budget[1]+budget[2]+estimate > budget[0]:
                raise BudgetDenied("AI budget exhausted")
            result=conn.execute("""INSERT INTO cvcloud.ai_reservations
                (tenant_id,owner_id,job_id,operation_id,lease_token,provider,model,reserved_microusd)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING operation_id""",
                (tenant,owner,uid(lease.job_id),operation_id,uid(lease.token),provider,model,estimate)).fetchone()
            if not result:
                raise BudgetDenied("AI operation already reserved or previous charge unsettled")
            conn.execute("""UPDATE cvcloud.ai_budgets SET reserved_microusd=reserved_microusd+%s
                WHERE tenant_id=%s""",(estimate,tenant))
        return Reservation(operation_id,estimate)

    def settle(self, principal, lease, *, operation_id, actual_microusd):
        """Settle once after verified billing; unknown billing keeps the hold.

        Actual cost may exceed the estimate: record it in full and deny further
        reservations when over cap. A stale lease cannot release a hold.
        """
        operation_id=uid(operation_id)
        actual=amount(actual_microusd,allow_zero=True)
        with self.repository.scoped(principal) as (conn,tenant,owner):
            budget=conn.execute("SELECT tenant_id FROM cvcloud.ai_budgets WHERE tenant_id=%s FOR UPDATE",(tenant,)).fetchone()
            if not budget:
                raise BudgetDenied("No budget configured")
            self._check_lease(conn,tenant,owner,lease)
            row=conn.execute("""SELECT reserved_microusd,actual_microusd
                FROM cvcloud.ai_reservations WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s
                AND job_id=%s AND lease_token=%s FOR UPDATE""",
                (tenant,owner,operation_id,uid(lease.job_id),uid(lease.token))).fetchone()
            if not row:
                raise BudgetDenied("AI operation not found")
            if row[1] is not None:
                if row[1] != actual:
                    raise BudgetDenied("Conflicting settlement")
                return False
            conn.execute("""UPDATE cvcloud.ai_reservations SET actual_microusd=%s,settled_at=clock_timestamp()
                WHERE tenant_id=%s AND owner_id=%s AND operation_id=%s""",(actual,tenant,owner,operation_id))
            conn.execute("""UPDATE cvcloud.ai_budgets SET reserved_microusd=reserved_microusd-%s,
                spent_microusd=spent_microusd+%s WHERE tenant_id=%s""",(row[0],actual,tenant))
            return True
