"""Durable write-once CRM fence; no raw candidate emails in journal."""
from contextlib import contextmanager
from hashlib import sha256
import hmac
from cloud.documents_jobs import uid
from cloud.jobadder_sandbox import CRMUnavailable

class AttemptJournal:
    def __init__(self,repository,key):
        if not isinstance(key,bytes) or len(key)!=32:
            raise ValueError("Dedicated stable journal HMAC key required")
        self.repository=repository
        self._key=key

    @contextmanager
    def guard(self,principal,account,job,email,*,lease_token):
        digest=hmac.new(self._key,
            (uid(principal.tenant_id)+"\0"+account+"\0"+email.strip().casefold()).encode("utf-8"),
            sha256).hexdigest()
        try:
            with self.repository.scoped(principal) as (conn,_,__):
                row=conn.execute("SELECT cvcloud.record_crm_attempt(%s::uuid,%s::uuid,%s,%s)",
                    (uid(job),uid(lease_token),account,digest)).fetchone()
                if row!=(True,):
                    raise CRMUnavailable("Attempt already recorded or lease invalid")
            # Committed before any network dispatch. Even if the process dies,
            # another job with this account/email cannot automatically write.
        except Exception:
            raise CRMUnavailable("CRM attempt refused; manual review required") from None
        yield
