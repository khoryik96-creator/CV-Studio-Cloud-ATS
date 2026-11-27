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

    def claim(self, principal):
        token = str(uuid4())
        with self.repository.scoped(principal) as (conn, tenant, owner):
            row = conn.execute("""WITH next_job AS (
                SELECT j.id FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.state='queued' AND u.active AND t.active
                ORDER BY j.created_at,j.id LIMIT 1 FOR UPDATE OF j SKIP LOCKED
            ) UPDATE cvcloud.jobs j
              SET state='running',lease_token=%s,lease_until=clock_timestamp()+make_interval(secs=>%s),
                  updated_at=clock_timestamp()
              FROM next_job n WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=n.id
              RETURNING j.id::text,j.document_id::text,j.module,j.lease_token::text""",
                (tenant,owner,token,LEASE_SECONDS,tenant,owner)).fetchone()
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
