"""Reviewed candidate creation with an injected tenant-bound CRM adapter."""

import hmac
import re

from cloud.documents_jobs import JobConflict, ScopeError
from cloud.file_extract import extract
from cloud.job_state import State
from cloud.private_storage import StoredObject
from cloud.report_storage import publish
from cloud.worker_supervision import LeaseSupervisor
from cvstudio_jobadder_write import _sanitize_jobadder_candidate_contacts

_EMAIL = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+")


class CreateProfile:
    def __init__(self, repository, storage, jobadder):
        self.repository = repository
        self.storage = storage
        self.jobadder = jobadder

    def _read(self, principal, document_id):
        row = self.repository.document(principal, document_id)
        if row is None:
            raise ScopeError("Candidate CV unavailable")
        _, mime, size, sha = row
        raw = self.storage.read_verified(principal.tenant_id, principal.user_id, document_id,
                                         StoredObject(size, sha, mime))
        text = extract(raw, mime).text
        header = [line.strip() for line in text.splitlines()[:12] if line.strip()]
        emails = {email.casefold() for line in header for email in _EMAIL.findall(line)}
        if not header or len(header[0]) > 200 or "@" in header[0] or len(emails) != 1:
            raise ValueError("Unclear candidate name or email")
        candidate = {"name": header[0], "email": emails.pop()}
        if _sanitize_jobadder_candidate_contacts(candidate) or not candidate["email"]:
            raise ValueError("Candidate email invalid")
        return candidate, raw, mime, sha

    def settings(self, principal):
        return self.jobadder.settings(principal)

    def prepare(self, principal, document_id):
        settings = self.settings(principal)
        candidate, _, _, digest = self._read(principal, document_id)
        return {"candidate": candidate, "confirmation": {"sha256": digest, "settings": settings}}

    def confirm(self, principal, document_id, key, confirmation):
        expected = self.prepare(principal, document_id)["confirmation"]
        if expected != confirmation:
            raise JobConflict("Candidate document or integration changed")
        return self.repository.enqueue(principal, document_id=document_id, module="create_profile",
                                       idempotency_key=key, profile=expected)

    def _record_dispatch(self, principal, lease):
        with self.repository.scoped(principal) as (conn, tenant, owner):
            row = conn.execute("""UPDATE cvcloud.jobs SET profile_started_at=clock_timestamp()
                WHERE tenant_id=%s AND owner_id=%s AND id=%s AND module='create_profile'
                AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()
                AND profile_started_at IS NULL
                RETURNING profile_confirmation""", (tenant, owner, lease.job_id, lease.token)).fetchone()
            if row is None:
                raise JobConflict("Profile attempt already recorded")
            return row[0]

    def _dispatch(self, principal, lease, settings, candidate, raw, mime):
        return self.jobadder.create_with_cv(principal, lease.job_id, settings, candidate, raw, mime)

    def run_claimed(self, principal, lease, workers):
        try:
            with LeaseSupervisor(lambda: workers.heartbeat(principal, lease), interval=20, deadline=600) as supervisor:
                candidate, raw, mime, digest = self._read(principal, lease.document_id)
                supervisor.check()
                if not workers.heartbeat(principal, lease):
                    raise JobConflict("Profile job lease lost")
                confirmation = self._record_dispatch(principal, lease)
                if not hmac.compare_digest(confirmation["sha256"], digest):
                    raise JobConflict("Candidate CV changed")
                result = self._dispatch(principal, lease, confirmation["settings"], candidate, raw, mime)
                supervisor.check()
                if not workers.heartbeat(principal, lease):
                    raise JobConflict("Profile job lease lost")
            publish(self.repository, principal, lease, result)
            return True
        except Exception:
            try:
                workers.finish(principal, lease, State.NEEDS_REVIEW)
            except Exception:
                pass
            return False

    def reports(self, principal, job_id=None):
        with self.repository.scoped(principal) as (conn, tenant, owner):
            scope = """FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.module='create_profile'
                AND j.profile_confirmation IS NOT NULL AND u.active AND t.active"""
            args = (tenant, owner)
            columns = """SELECT j.id::text, j.state, j.created_at, j.profile_started_at,
                         j.updated_at, j.profile_result """
            if job_id is None:
                rows = conn.execute(columns + scope + " ORDER BY j.created_at DESC, j.id DESC LIMIT 25", args).fetchall()
            else:
                rows = conn.execute(columns + scope + " AND j.id=%s", (*args, job_id)).fetchall()
            items = [{"job_id": jid, "state": state, "confirmed_at": confirmed.isoformat(),
                      "attempted_at": attempted.isoformat() if attempted else None,
                      "updated_at": updated.isoformat(), "result": result}
                     for jid, state, confirmed, attempted, updated, result in rows]
            if job_id is None:
                return {"items": items}
            if not items:
                raise ScopeError("Profile job unavailable")
            return items[0]

    def reconcile(self, principal, job_id):
        with self.repository.scoped(principal) as (conn, tenant, owner):
            row = conn.execute("""SELECT j.profile_confirmation FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s AND j.module='create_profile'
                AND j.state='needs_review' AND j.profile_started_at IS NOT NULL AND u.active AND t.active
                FOR UPDATE OF j FOR SHARE OF u,t""", (tenant, owner, job_id)).fetchone()
            if row is None:
                raise ScopeError("Reconciliation unavailable")
            result = self.jobadder.reconcile(principal, job_id, row[0]["settings"])
            if result is not None:
                from psycopg.types.json import Jsonb
                conn.execute("""UPDATE cvcloud.jobs SET profile_result=%s, state='succeeded', updated_at=clock_timestamp()
                    WHERE tenant_id=%s AND owner_id=%s AND id=%s""", (Jsonb(result), tenant, owner, job_id))
        return self.reports(principal, job_id)
