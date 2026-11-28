"""Publish verified Word bytes before committing a lease-fenced result.

An object is immutable and named by a new UUID; a crash before DB commit can
leave an orphan but never a completed job referencing unpublished bytes.
Uncertain commits must not trigger deletion. A future reconciler must compare
against metadata after a grace period. No public paths or unauthenticated API.
"""
from dataclasses import dataclass
from io import BytesIO
from uuid import uuid4
from cloud.documents_jobs import uid
from cloud.private_storage import StoredObject,DOCX
from cloud.cv_engine import Result

class OutputError(ValueError):
    pass

@dataclass(frozen=True,repr=False)
class Download:
    document: bytes
    requires_review: bool

class JobOutputs:
    def __init__(self, repository, storage):
        self.repository=repository
        self.storage=storage

    def publish(self, principal, lease, result):
        if not isinstance(result,Result) or type(result.requires_review) is not bool:
            raise OutputError("invalid_job_result")
        job_id,token=uid(lease.job_id),uid(lease.token)
        # Validate ownership and lease before writing any bytes.
        with self.repository.scoped(principal) as (conn,tenant,owner):
            row=conn.execute("""SELECT j.module,j.document_id::text FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s AND j.state='running'
                AND j.lease_token=%s AND j.lease_until>clock_timestamp() AND u.active AND t.active""",(tenant,owner,job_id,token)).fetchone()
            if not row or tuple(row)!=(lease.module,uid(lease.document_id)) or lease.module not in ("cv_formatting","cv_blinding"):
                raise OutputError("invalid_output_lease")
        object_id=str(uuid4())
        info=self.storage.put(tenant,owner,object_id,BytesIO(result.document),DOCX)
        review=result.requires_review or lease.module=="cv_blinding"
        with self.repository.scoped(principal) as (conn,tenant,owner):
            if not self.repository.lock_active_account(conn,tenant,owner):
                raise OutputError("output_lease_lost")
            active=conn.execute("""SELECT j.id FROM cvcloud.jobs j
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
                JOIN cvcloud.tenants t ON t.id=j.tenant_id
                WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s AND j.state='running'
                AND j.lease_token=%s AND j.lease_until>clock_timestamp()
                AND u.active AND t.active FOR UPDATE OF j""",(tenant,owner,job_id,token)).fetchone()
            if not active:
                raise OutputError("output_lease_lost")
            pending=conn.execute("""SELECT 1 FROM cvcloud.ai_reservations WHERE tenant_id=%s
                AND owner_id=%s AND job_id=%s AND settled_at IS NULL LIMIT 1""",(tenant,owner,job_id)).fetchone()
            if pending:
                raise OutputError("unsettled_ai_charge")
            conn.execute("""INSERT INTO cvcloud.job_outputs
                (tenant_id,owner_id,job_id,object_id,byte_size,sha256,requires_review)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""",(tenant,owner,job_id,object_id,info.size,info.digest,review))
            changed=conn.execute("""UPDATE cvcloud.jobs SET state=%s,lease_token=NULL,lease_until=NULL,
                updated_at=clock_timestamp() WHERE tenant_id=%s AND owner_id=%s AND id=%s
                AND state='running' AND lease_token=%s AND lease_until>clock_timestamp()""",
                ("needs_review" if review else "succeeded",tenant,owner,job_id,token))
            if changed.rowcount!=1:
                raise OutputError("output_lease_lost")
        return object_id

    def download(self,principal,job_id):
        with self.repository.scoped(principal) as (conn,tenant,owner):
            row=conn.execute("""SELECT o.object_id::text,o.byte_size,o.sha256,o.requires_review
                FROM cvcloud.job_outputs o JOIN cvcloud.jobs j ON (j.tenant_id,j.id,j.owner_id)=(o.tenant_id,o.job_id,o.owner_id)
                JOIN cvcloud.users u ON (u.tenant_id,u.id)=(o.tenant_id,o.owner_id)
                JOIN cvcloud.tenants t ON t.id=o.tenant_id
                WHERE o.tenant_id=%s AND o.owner_id=%s AND o.job_id=%s
                AND j.state IN ('succeeded','needs_review') AND u.active AND t.active""",(tenant,owner,uid(job_id))).fetchone()
            if not row:
                return None
            object_id,size,digest,review=row
            raw=self.storage.read_verified(tenant,owner,object_id,StoredObject(size,digest,DOCX))
            return Download(raw,review)
