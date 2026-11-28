"""Operator-only issuance and narrowly scoped staff token redemption.

No live HTTP route or deployment wiring in this batch. Existing account
revocation/version checks apply to persistent browser sessions. No owner or
administrator enrollment. Raw codes must be delivered privately, not logged.
"""
from datetime import timedelta
from secrets import token_urlsafe
from uuid import uuid4
from cloud.auth import TOKEN,TENANT,digest,password_hash
from cloud.deploy.online_owner import verify_owner_database
from cloud.account_admin import _email

STAFF_TTL=timedelta(days=90)

def issue_staff(connect,*,tenant,email):
    if not isinstance(tenant,str) or not TENANT.fullmatch(tenant):
        raise ValueError("Invalid organisation")
    email=_email(email)
    token=token_urlsafe(32)
    with connect() as conn:
        verify_owner_database(conn)
        row=conn.execute("SELECT id,auth_epoch FROM cvcloud.tenants WHERE slug=%s AND active FOR UPDATE",(tenant,)).fetchone()
        if not row:
            raise ValueError("Unknown organisation")
        tid,epoch=row
        old=conn.execute("SELECT id,role,active,credential_version FROM cvcloud.users WHERE tenant_id=%s AND email_normalized=%s FOR UPDATE",(tid,email)).fetchone()
        if old:
            user,role,active,version=old
            if role!="recruiter" or not active:
                raise ValueError("Active recruiter required")
        else:
            if conn.execute("SELECT count(*) FROM cvcloud.users WHERE tenant_id=%s",(tid,)).fetchone()[0]>=100:
                raise ValueError("Organisation account limit exceeded")
            user=str(uuid4())
            version=conn.execute("""INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role)
                VALUES (%s,%s,%s,%s,'recruiter') RETURNING credential_version""",
                (tid,user,email,password_hash(token_urlsafe(32)))).fetchone()[0]
        conn.execute("""INSERT INTO cvcloud.staff_enrollments
            (tenant_id,user_id,token_digest,credential_version,tenant_epoch,expires_at)
            VALUES (%s,%s,%s,%s,%s,clock_timestamp()+interval '24 hours')
            ON CONFLICT (tenant_id,user_id) DO UPDATE SET token_digest=EXCLUDED.token_digest,
            credential_version=EXCLUDED.credential_version,tenant_epoch=EXCLUDED.tenant_epoch,
            expires_at=EXCLUDED.expires_at""",(tid,user,digest(token),version,epoch))
    return token

def redeem_staff(auth,token,source):
    if not isinstance(source,str) or not 1<=len(source)<=128:
        return None
    now=auth.clock()
    if not auth.store.consume_attempt(digest("staff:source:"+source),now):
        return None
    if not isinstance(token,str) or not TOKEN.fullmatch(token):
        return None
    if not auth.store.consume_attempt(digest("staff:token:"+token),now):
        return None
    raw,csrf=token_urlsafe(32),token_urlsafe(32)
    with auth.store.connect() as conn:
        accepted=conn.execute("SELECT cvcloud.redeem_staff_enrollment(%s,%s,%s)",(digest(token),digest(raw),csrf)).fetchone()
    return raw if accepted==(True,) else None
