"""Owner-scoped document reads and lease-fenced publication of structured reports."""

from psycopg.types.json import Jsonb

from cloud.file_extract import extract
from cloud.private_storage import StoredObject

RESULT_COLUMN = {
    "cv_scoring": "scoring_result",
    "blind_jd": "report_result",
    "company_profile": "report_result",
    "create_profile": "profile_result",
}


def read_document(repository, storage, principal, document_id):
    row = repository.document(principal, document_id)
    if row is None:
        raise ValueError("document_not_found")
    _, media_type, size, digest = row
    raw = storage.read_verified(principal.tenant_id, principal.user_id, document_id,
                                StoredObject(size, digest, media_type))
    return extract(raw, media_type).text


def publish(repository, principal, lease, result):
    result_column = RESULT_COLUMN[lease.module]
    with repository.scoped(principal) as (conn, tenant, owner):
        if not repository.lock_active_account(conn,tenant,owner):
            raise ValueError("report_lease_lost")
        active = conn.execute("""SELECT j.id FROM cvcloud.jobs j
            JOIN cvcloud.users u ON (u.tenant_id,u.id)=(j.tenant_id,j.owner_id)
            JOIN cvcloud.tenants t ON t.id=j.tenant_id
            WHERE j.tenant_id=%s AND j.owner_id=%s AND j.id=%s AND j.state='running'
            AND j.lease_token=%s AND j.lease_until>clock_timestamp() AND u.active AND t.active
            FOR UPDATE OF j""", (tenant, owner, lease.job_id, lease.token)).fetchone()
        if active is None:
            raise ValueError("report_lease_lost")
        if conn.execute("""SELECT 1 FROM cvcloud.ai_reservations
            WHERE tenant_id=%s AND owner_id=%s AND job_id=%s AND settled_at IS NULL LIMIT 1""",
            (tenant, owner, lease.job_id)).fetchone():
            raise ValueError("unsettled_ai_charge")
        changed = conn.execute("""UPDATE cvcloud.jobs SET """ + result_column + """=%s, state='succeeded',
            lease_token=NULL, lease_until=NULL, updated_at=clock_timestamp()
            WHERE tenant_id=%s AND owner_id=%s AND id=%s AND lease_token=%s AND lease_until>clock_timestamp()""",
            (Jsonb(result), tenant, owner, lease.job_id, lease.token))
        if changed.rowcount != 1:
            raise ValueError("report_lease_lost")
