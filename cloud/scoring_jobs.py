"""Fenced scoring execution and owner-scoped retrieval of evidence reports."""

from psycopg.types.json import Jsonb

from cloud.file_extract import extract
from cloud.job_state import State
from cloud.private_storage import StoredObject
from cloud.scoring_contract import ScoringError, parse_rubric
from cloud.scoring_execution import execute
from cloud.worker_supervision import LeaseSupervisor


def _read_document(repository, storage, principal, document_id):
    row = repository.document(principal, document_id)
    if row is None:
        raise ScoringError("document_not_found")
    _, media_type, size, digest = row
    raw = storage.read_verified(principal.tenant_id, principal.user_id, document_id,
                                StoredObject(size, digest, media_type))
    return extract(raw, media_type).text


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
            cv = _read_document(repository, storage, principal, lease.document_id)
            jd = _read_document(repository, storage, principal, jd_id)
            result = execute(principal=principal, lease=lease, ledger=ledger, policy=policy, transport=transport,
                             cv=cv, jd=jd, criteria=parse_rubric(criteria), check=supervisor.check)
            supervisor.check()
            if not workers.heartbeat(principal, lease):
                raise ScoringError("scoring_lease_lost")
        with repository.scoped(principal) as (conn, tenant, owner):
            active = conn.execute("""SELECT j.id FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s AND j.state='running'
                AND j.lease_token=%s AND j.lease_until>clock_timestamp() AND u.active AND t.active
                FOR UPDATE OF j FOR SHARE OF u,t""", (tenant, owner, lease.job_id, lease.token)).fetchone()
            if active is None:
                raise ScoringError("scoring_lease_lost")
            if conn.execute("""SELECT 1 FROM cvcloud.ai_reservations
                WHERE tenant_id=%s AND owner_id=%s AND job_id=%s AND settled_at IS NULL LIMIT 1""",
                (tenant, owner, lease.job_id)).fetchone():
                raise ScoringError("unsettled_ai_charge")
            changed = conn.execute("""UPDATE cvcloud.jobs SET scoring_result=%s, state='succeeded',
                lease_token=NULL, lease_until=NULL, updated_at=clock_timestamp()
                WHERE tenant_id=%s AND owner_id=%s AND id=%s AND lease_until>clock_timestamp()""",
                (Jsonb(result), tenant, owner, lease.job_id))
            if changed.rowcount != 1:
                raise ScoringError("scoring_lease_lost")
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
