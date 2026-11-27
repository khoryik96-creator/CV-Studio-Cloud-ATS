"""Tenant + owner-scoped metadata and durable job state. No HTTP routes yet."""
from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4
import re

from cloud.auth import Principal, ROLES
from cloud.modules import SELECTED_MODULES
from cloud.job_options import Options

MEDIA_TYPES = frozenset({
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
})
MAX_BYTES = 32 * 1024 * 1024

class ScopeError(ValueError):
    pass

class JobConflict(ValueError):
    pass

def uid(value):
    return str(UUID(str(value)))

class DocumentJobs:
    """Every query derives its tenant and owner from a server-resolved principal.

    A connection context must represent a new transaction. RLS settings are
    transaction-local and never persist across connection-pool checkouts.
    Workers use a separate, narrowly scoped service (not implemented here).
    """
    def __init__(self, connect):
        self.connect = connect

    @contextmanager
    def scoped(self, principal):
        if not isinstance(principal, Principal) or principal.role not in ROLES:
            raise ScopeError("Authenticated principal required")
        tenant, user = uid(principal.tenant_id), uid(principal.user_id)
        with self.connect() as conn:
            conn.execute("SELECT set_config('cvcloud.tenant_id',%s,true),set_config('cvcloud.user_id',%s,true)", (tenant,user))
            yield conn, tenant, user

    def register_document(self, principal, *, media_type, byte_size, sha256):
        """Register metadata only after a future upload service validates/stores bytes."""
        if media_type not in MEDIA_TYPES or type(byte_size) is not int or not 1 <= byte_size <= MAX_BYTES or not isinstance(sha256,str) or not re.fullmatch(r"[a-f0-9]{64}",sha256):
            raise ValueError("Invalid document metadata")
        doc_id = str(uuid4())
        with self.scoped(principal) as (conn,tenant,user):
            conn.execute("""INSERT INTO cvcloud.documents
                (tenant_id,id,owner_id,media_type,byte_size,sha256) VALUES (%s,%s,%s,%s,%s,%s)""",
                (tenant,doc_id,user,media_type,byte_size,sha256))
        return doc_id

    def document(self, principal, document_id):
        with self.scoped(principal) as (conn,tenant,user):
            return conn.execute("""SELECT id::text,media_type,byte_size,sha256
                FROM cvcloud.documents WHERE tenant_id=%s AND owner_id=%s AND id=%s""",
                (tenant,user,uid(document_id))).fetchone()

    def enqueue(self, principal, *, document_id, module, idempotency_key, options=Options()):
        if module not in SELECTED_MODULES or not isinstance(options,Options):
            raise ValueError("Module or options invalid")
        options.validate(module)
        document_id, key = uid(document_id), uid(idempotency_key)
        with self.scoped(principal) as (conn,tenant,user):
            # Lock the account to serialize this user's queue admission. Per-user
            # and tenant-wide quotas and storage limits will be added separately.
            active=conn.execute("""SELECT u.id FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active FOR UPDATE OF u""",(tenant,user)).fetchone()
            if not active:
                raise ScopeError("Account is inactive")
            prior=conn.execute("""SELECT id::text,document_id::text,module,alignment,correct_language,neutral_gender FROM cvcloud.jobs
                WHERE tenant_id=%s AND owner_id=%s AND idempotency_key=%s""",(tenant,user,key)).fetchone()
            if prior:
                if tuple(prior[1:]) != (document_id,module,options.alignment,options.correct_language,options.neutral_gender):
                    raise JobConflict("Idempotency key already used for a different request")
                return prior[0]
            doc=conn.execute("SELECT id FROM cvcloud.documents WHERE tenant_id=%s AND owner_id=%s AND id=%s",(tenant,user,document_id)).fetchone()
            if not doc:
                raise ScopeError("Document not found")
            count=conn.execute("""SELECT count(*) FROM cvcloud.jobs WHERE tenant_id=%s AND owner_id=%s
                AND state IN ('queued','running','needs_review')""",(tenant,user)).fetchone()[0]
            if count >= 10:
                raise JobConflict("Outstanding job limit reached")
            job_id=str(uuid4())
            conn.execute("""INSERT INTO cvcloud.jobs (tenant_id,id,owner_id,document_id,module,idempotency_key,alignment,correct_language,neutral_gender)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(tenant,job_id,user,document_id,module,key,options.alignment,options.correct_language,options.neutral_gender))
            return job_id

    def job(self, principal, job_id):
        with self.scoped(principal) as (conn,tenant,user):
            return conn.execute("""SELECT id::text,module,state,document_id::text
                FROM cvcloud.jobs WHERE tenant_id=%s AND owner_id=%s AND id=%s""",
                (tenant,user,uid(job_id))).fetchone()

    def history(self, principal, *, kind, limit=25, before=None):
        """Bounded owner-only history; UUID cursor must belong to this listing."""
        if kind not in ("jobs","documents") or type(limit) is not int or not 1<=limit<=50:
            raise ValueError("Invalid history request")
        cursor=uid(before) if before is not None else None
        with self.scoped(principal) as (conn,tenant,owner):
            if not conn.execute("""SELECT 1 FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.active AND t.active
                FOR SHARE OF u,t""",(tenant,owner)).fetchone():
                raise ScopeError("Account unavailable")
            # Only the two static table/query definitions below can be selected.
            if kind=="jobs":
                table="cvcloud.jobs"
                where=" AND module IN ('cv_formatting','cv_blinding')"
                fields="""id::text,document_id::text,module,state,created_at,updated_at,
                    EXISTS (SELECT 1 FROM cvcloud.job_outputs o
                    WHERE o.tenant_id=jobs.tenant_id AND o.owner_id=jobs.owner_id AND o.job_id=jobs.id)"""
            else:
                table="cvcloud.documents"
                where=""
                fields="""id::text,media_type,byte_size,created_at,
                    EXISTS (SELECT 1 FROM cvcloud.jobs j WHERE j.tenant_id=documents.tenant_id
                    AND j.owner_id=documents.owner_id AND j.document_id=documents.id)"""
            params=(tenant,owner)
            clause=" WHERE tenant_id=%s AND owner_id=%s"+where
            if cursor is not None:
                prior=conn.execute("SELECT created_at,id FROM "+table+clause+" AND id=%s",(*params,cursor)).fetchone()
                if not prior:
                    raise ScopeError("History cursor unavailable")
                clause+=" AND (created_at,id)<(%s,%s)"
                params=(*params,*prior)
            rows=conn.execute("SELECT "+fields+" FROM "+table+clause+
                " ORDER BY created_at DESC,id DESC LIMIT %s",(*params,limit+1)).fetchall()
            more=len(rows)>limit
            rows=rows[:limit]
            if kind=="jobs":
                items=[dict(job_id=j,document_id=d,module=m,state=s,created_at=c.isoformat(),updated_at=u.isoformat(),
                    output_available=bool(o) and s in ("succeeded","needs_review")) for j,d,m,s,c,u,o in rows]
            else:
                items=[dict(document_id=d,media_type=m,byte_size=n,created_at=c.isoformat(),has_jobs=bool(j))
                    for d,m,n,c,j in rows]
            return {"items":items,"next_cursor":rows[-1][0] if more else None}

    def options(self, principal, job_id):
        with self.scoped(principal) as (conn,tenant,user):
            row=conn.execute("""SELECT alignment,correct_language,neutral_gender FROM cvcloud.jobs
                WHERE tenant_id=%s AND owner_id=%s AND id=%s""",(tenant,user,uid(job_id))).fetchone()
            return Options(*row) if row else None
