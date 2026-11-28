"""Fictional JobAdder adapter with independent transactions and no network."""

import hashlib
import hmac
from uuid import uuid4

KEY = "local-synthetic-jobadder-fixture-key"
ACCOUNT_SECRET_ENV = "CVCLOUD_FIXTURE_JOBADDER_KEY"


def digest(tenant, key):
    return hmac.new(key.encode("ascii"), tenant.encode("ascii"), hashlib.sha256).hexdigest()


class JobAdderFixture:
    def __init__(self, repository, key):
        if key != KEY:
            raise ValueError("Synthetic JobAdder key required")
        self.repository = repository
        self.key = key

    def _connect(self, conn, tenant):
        row = conn.execute("""SELECT account_id::text, credential_digest, revision FROM cvcloud.jobadder_fixture_config
            WHERE tenant_id=%s AND enabled""", (tenant,)).fetchone()
        if not row or not hmac.compare_digest(digest(tenant, self.key), row[1]):
            raise ValueError("integration_unavailable")
        return {"account_id": row[0], "revision": row[2]}

    def settings(self, principal):
        with self.repository.scoped(principal) as (conn, tenant, _):
            return self._connect(conn, tenant)

    def _operation(self, conn, tenant, owner, job_id):
        row = conn.execute("""SELECT candidate_id::text, duplicate FROM cvcloud.jobadder_fixture_operations
            WHERE tenant_id=%s AND owner_id=%s AND job_id=%s""", (tenant, owner, job_id)).fetchone()
        if row is not None:
            candidate_id, duplicate = row
            return {"outcome": "duplicate" if duplicate else "created", "candidate_id": candidate_id,
                    "cv_uploaded": not duplicate}

    def reconcile(self, principal, job_id, settings):
        with self.repository.scoped(principal) as (conn, tenant, owner):
            if self._connect(conn, tenant) != settings:
                raise ValueError("integration_configuration_changed")
            return self._operation(conn, tenant, owner, job_id)

    def create_with_cv(self, principal, job_id, settings, candidate, raw, mime):
        with self.repository.scoped(principal) as (conn, tenant, owner):
            if self._connect(conn, tenant) != settings:
                raise ValueError("integration_configuration_changed")
            # One mock transaction represents durable confirmation from the
            # remote API. Unique candidate email also fences concurrent owners.
            existing = self._operation(conn, tenant, owner, job_id)
            if existing:
                return existing
            candidate_id = str(uuid4())
            created = conn.execute("""INSERT INTO cvcloud.jobadder_fixture_candidates
                (tenant_id,id,email,candidate_name,cv,mime) VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tenant_id,email) DO NOTHING RETURNING id""",
                (tenant, candidate_id, candidate["email"], candidate["name"], raw, mime)).fetchone()
            conn.execute("""INSERT INTO cvcloud.jobadder_fixture_operations
                (tenant_id,owner_id,job_id,candidate_id,duplicate) VALUES (%s,%s,%s,%s,%s)""",
                (tenant, owner, job_id, candidate_id if created else None, not bool(created)))
            return self._operation(conn, tenant, owner, job_id)
