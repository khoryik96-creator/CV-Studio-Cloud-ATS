"""Fenced scoring execution and owner-scoped retrieval of evidence reports."""

from cloud.job_state import State
from cloud.report_storage import publish, read_document
from cloud.scoring_contract import ScoringError, parse_rubric
from cloud.scoring_execution import execute
from cloud.worker_supervision import LeaseSupervisor


def run_claimed(*, principal, lease, repository, storage, workers, ledger, policy, transport):
    try:
        with LeaseSupervisor(lambda: workers.heartbeat(principal, lease), interval=20, deadline=600) as supervisor:
            with repository.scoped(principal) as (conn, tenant, owner):
                row = conn.execute("""SELECT scoring_jd_id::text, scoring_criteria FROM cvcloud.jobs
                    WHERE tenant_id=%s AND owner_id=%s AND id=%s AND document_id=%s AND module='cv_scoring'
                    AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()""",
                    (tenant, owner, lease.job_id, lease.document_id, lease.token)).fetchone()
            if row is None:
                raise ScoringError("invalid_scoring_lease")
            jd_id, criteria = row
            cv = read_document(repository, storage, principal, lease.document_id)
            jd = read_document(repository, storage, principal, jd_id)
            result = execute(principal=principal, lease=lease, ledger=ledger, policy=policy, transport=transport,
                             cv=cv, jd=jd, criteria=parse_rubric(criteria), check=supervisor.check)
            supervisor.check()
            if not workers.heartbeat(principal, lease):
                raise ScoringError("scoring_lease_lost")
        publish(repository, principal, lease, result)
        return True
    except Exception:
        try:
            workers.finish(principal, lease, State.NEEDS_REVIEW)
        except Exception:
            pass
        return False


def reports(repository, principal, job_id=None):
    with repository.scoped(principal) as (conn, tenant, owner):
        scope = """FROM cvcloud.jobs j
            JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
            JOIN cvcloud.tenants t ON t.id=j.tenant_id
            WHERE j.tenant_id=%s AND j.owner_id=%s AND j.module='cv_scoring'
            AND j.scoring_jd_id IS NOT NULL AND u.active AND t.active"""
        if job_id is None:
            rows = conn.execute("SELECT j.id::text, j.state, j.created_at " + scope + " ORDER BY j.created_at DESC, j.id DESC LIMIT 25", (tenant, owner)).fetchall()
            return {"items": [{"job_id": jid, "state": state, "created_at": created.isoformat()}
                              for jid, state, created in rows]}
        row = conn.execute("SELECT j.id::text, j.state, j.scoring_result " + scope + " AND j.id=%s",
                           (tenant, owner, job_id)).fetchone()
        if row is not None:
            return {"job_id": row[0], "state": row[1], "assessment": row[2]}
