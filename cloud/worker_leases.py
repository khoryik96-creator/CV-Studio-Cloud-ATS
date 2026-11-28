"""Fenced lease repository. Internal only; not an autonomous worker or paid AI client.

A trusted scheduler must supply a server-derived principal. Each operation
uses the existing owner-scoped RLS transaction. Expiry is terminal for an
attempt: uncertain external work is marked needs_review, not replayed.
"""
from dataclasses import dataclass
from uuid import uuid4
from cloud.documents_jobs import uid
from cloud.job_state import State

LEASE_SECONDS = 120

@dataclass(frozen=True)
class Lease:
    job_id: str
    document_id: str
    module: str
    token: str

class WorkerLeases:
    def __init__(self, repository):
        self.repository = repository

    def claim(self, principal, *, cv_only=False, include_scoring=False, include_reports=False):
        if type(cv_only) is not bool or type(include_scoring) is not bool or type(include_reports) is not bool:
            raise ValueError("Invalid claim filter")
        token = str(uuid4())
        with self.repository.scoped(principal) as (conn, tenant, owner):
            # Serialize claims for an owner across worker processes. Admission
            # of a queued job also locks this user row.
            active=conn.execute("""SELECT u.id FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active FOR UPDATE OF u""",(tenant,owner)).fetchone()
            if not active:
                return None
            row = conn.execute("""WITH next_job AS (
                SELECT j.id FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.state='queued' AND u.active AND t.active
                AND (NOT %s OR j.module IN ('cv_formatting','cv_blinding')
                    OR (%s AND j.module='cv_scoring' AND j.scoring_jd_id IS NOT NULL)
                    OR (%s AND j.module IN ('blind_jd','company_profile') AND j.report_options IS NOT NULL))
                AND NOT EXISTS (SELECT 1 FROM cvcloud.jobs running WHERE running.tenant_id=j.tenant_id
                    AND running.owner_id=j.owner_id AND running.state='running')
                ORDER BY j.created_at,j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED
            ) UPDATE cvcloud.jobs j
              SET state='running',lease_token=%s,lease_until=clock_timestamp()+make_interval(secs=>%s),
                  updated_at=clock_timestamp()
              FROM next_job n WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=n.id
              RETURNING j.id::text,j.document_id::text,j.module,j.lease_token::text""",
                (tenant,owner,cv_only,include_scoring,include_reports,token,LEASE_SECONDS,tenant,owner)).fetchone()
        return Lease(*row) if row else None

    def heartbeat(self, principal, lease):
        with self.repository.scoped(principal) as (conn,tenant,owner):
            result=conn.execute("""UPDATE cvcloud.jobs SET lease_until=clock_timestamp()+make_interval(secs=>%s),
                updated_at=clock_timestamp() WHERE tenant_id=%s AND owner_id=%s AND id=%s
                AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()
                AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                    WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active)""",
                (LEASE_SECONDS,tenant,owner,uid(lease.job_id),uid(lease.token),tenant,owner))
            return result.rowcount == 1

    def finish(self, principal, lease, target):
        target = State(target)
        if target not in (State.SUCCEEDED,State.FAILED,State.NEEDS_REVIEW):
            raise ValueError("Invalid terminal state")
        with self.repository.scoped(principal) as (conn,tenant,owner):
            # Unknown provider billing cannot be represented as a clean success/failure.
            # Reservation and completion both lock the job row before changing it.
            active=conn.execute("""SELECT module,(scoring_jd_id IS NOT NULL OR report_options IS NOT NULL) FROM cvcloud.jobs WHERE tenant_id=%s AND owner_id=%s
                AND id=%s AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()
                FOR UPDATE""",(tenant,owner,uid(lease.job_id),uid(lease.token))).fetchone()
            if not active:
                return False
            # Document-producing jobs must publish through JobOutputs, not
            # transition to success without a durable downloadable artifact.
            if target is State.SUCCEEDED and (active[0] in ("cv_formatting","cv_blinding") or active[1]):
                return False
            pending=conn.execute("""SELECT 1 FROM cvcloud.ai_reservations WHERE tenant_id=%s
                AND owner_id=%s AND job_id=%s AND settled_at IS NULL LIMIT 1""",
                (tenant,owner,uid(lease.job_id))).fetchone()
            if pending and target is not State.NEEDS_REVIEW:
                return False
            result=conn.execute("""UPDATE cvcloud.jobs SET state=%s,lease_token=NULL,lease_until=NULL,
                updated_at=clock_timestamp() WHERE tenant_id=%s AND owner_id=%s AND id=%s
                AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()
                AND EXISTS (SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                    WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active)""",
                (target.value,tenant,owner,uid(lease.job_id),uid(lease.token),tenant,owner))
            return result.rowcount == 1

    def expire(self, principal):
        with self.repository.scoped(principal) as (conn,tenant,owner):
            result=conn.execute("""UPDATE cvcloud.jobs SET state='needs_review',lease_token=NULL,
                lease_until=NULL,updated_at=clock_timestamp()
                WHERE tenant_id=%s AND owner_id=%s AND state='running'
                AND lease_until<=clock_timestamp()""",(tenant,owner))
            return result.rowcount
