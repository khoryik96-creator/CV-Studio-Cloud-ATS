"""Internal tenant administration service. No public provisioning endpoint.

Owner manages admins/recruiters; admin manages recruiters only. No owner
creation, self-modification, deletion, cross-tenant targeting or password
retrieval. The composition root must supply dedicated least-privilege DB access.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import uuid4
from cloud.auth import password_hash
from cloud.documents_jobs import uid

class AccountAdminError(ValueError):
    pass

@dataclass(frozen=True,repr=False)
class AccountStatus:
    user_id: str
    email: str
    role: str
    active: bool
    revision: int

def _email(value):
    if not isinstance(value,str) or len(value)>512:
        raise AccountAdminError("invalid_email")
    value=value.strip().casefold()
    if not 3<=len(value)<=254 or value.count("@")!=1 or not all(value.split("@")) or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in value):
        raise AccountAdminError("invalid_email")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise AccountAdminError("invalid_email") from None
    return value

def _hash(value):
    try:
        if not isinstance(value,str) or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError()
        value.encode("utf-8")
        return password_hash(value)
    except (ValueError,UnicodeError):
        raise AccountAdminError("invalid_password") from None

def _revision(value):
    if type(value) is not int or not 1<=value<2**63-1:
        raise AccountAdminError("invalid_revision")
    return value

def _allowed(actor,target):
    return target=="recruiter" or (actor=="owner" and target=="admin")

class AccountAdmin:
    def __init__(self,repository):
        self.repository=repository

    @contextmanager
    def _scope(self,principal):
        # Serialize administrative mutations per tenant, then recheck the
        # actor under lock. Never trust the cached principal's role alone.
        with self.repository.scoped(principal) as (conn,tenant,actor):
            active=conn.execute("SELECT id FROM cvcloud.tenants WHERE id=%s AND active FOR UPDATE",(tenant,)).fetchone()
            row=conn.execute("SELECT role FROM cvcloud.users WHERE tenant_id=%s AND id=%s AND active FOR SHARE",(tenant,actor)).fetchone()
            if not active or not row or row[0] not in ("owner","admin"):
                raise AccountAdminError("account_admin_denied")
            yield conn,tenant,actor,row[0]

    @staticmethod
    def _audit(conn,tenant,actor,target,action):
        conn.execute("""INSERT INTO cvcloud.account_audit
            (tenant_id,event_id,actor_id,target_id,action) VALUES (%s,%s,%s,%s,%s)""",
            (tenant,str(uuid4()),actor,target,action))

    def list_accounts(self,principal):
        with self._scope(principal) as (conn,tenant,actor,role):
            rows=conn.execute("""SELECT id::text,email_normalized,role,active,credential_version
                FROM cvcloud.users WHERE tenant_id=%s ORDER BY email_normalized,id LIMIT 101""",(tenant,)).fetchall()
            if len(rows)>100:
                raise AccountAdminError("account_limit_exceeded")
            return tuple(AccountStatus(*r) for r in rows if r[0]==actor or _allowed(role,r[2]))

    def create(self,principal,*,email,role,password):
        email=_email(email)
        with self._scope(principal) as (conn,tenant,actor,actor_role):
            if not _allowed(actor_role,role):
                raise AccountAdminError("account_admin_denied")
            count=conn.execute("SELECT count(*) FROM cvcloud.users WHERE tenant_id=%s",(tenant,)).fetchone()[0]
            if count>=100:
                raise AccountAdminError("account_limit_exceeded")
            user=str(uuid4())
            hashed=_hash(password)
            row=conn.execute("""INSERT INTO cvcloud.users
                (tenant_id,id,email_normalized,password_hash,role)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING
                RETURNING id::text,email_normalized,role,active,credential_version""",
                (tenant,user,email,hashed,role)).fetchone()
            if not row:
                raise AccountAdminError("account_conflict")
            self._audit(conn,tenant,actor,user,"create")
            return AccountStatus(*row)

    def change(self,principal,*,user_id,expected_revision,action,value=None):
        user,expected=uid(user_id),_revision(expected_revision)
        if action not in ("role_change","suspend","reactivate","password_reset","revoke_sessions"):
            raise AccountAdminError("invalid_action")
        if action in ("suspend","reactivate","revoke_sessions") and value is not None:
            raise AccountAdminError("invalid_action")
        with self._scope(principal) as (conn,tenant,actor,actor_role):
            if user==actor:
                raise AccountAdminError("account_admin_denied")
            current=conn.execute("""SELECT role,active,credential_version FROM cvcloud.users
                WHERE tenant_id=%s AND id=%s FOR UPDATE""",(tenant,user)).fetchone()
            if not current or not _allowed(actor_role,current[0]):
                raise AccountAdminError("account_admin_denied")
            if current[2]!=expected:
                raise AccountAdminError("account_conflict")
            pending=conn.execute("SELECT 1 FROM cvcloud.account_challenges WHERE tenant_id=%s AND user_id=%s AND purpose='invite'",(tenant,user)).fetchone()
            if pending:
                raise AccountAdminError("account_admin_denied")
            if action=="role_change":
                if not _allowed(actor_role,value) or value==current[0]:
                    raise AccountAdminError("invalid_role_change")
                sql,params="role=%s",(value,)
            elif action=="password_reset":
                sql,params="password_hash=%s",(_hash(value),)
            elif action in ("suspend","reactivate"):
                state=action=="reactivate"
                if state==current[1]:
                    raise AccountAdminError("invalid_state_change")
                sql,params="active=%s",(state,)
            else:
                sql,params="credential_version=credential_version+1",()
            # All SQL fragments above are fixed constants, never caller strings.
            row=conn.execute("UPDATE cvcloud.users SET "+sql+"""
                WHERE tenant_id=%s AND id=%s AND credential_version=%s
                RETURNING id::text,email_normalized,role,active,credential_version""",
                (*params,tenant,user,expected)).fetchone()
            if not row or row[4]!=expected+1:
                raise AccountAdminError("account_conflict")
            conn.execute("DELETE FROM cvcloud.sessions WHERE tenant_id=%s AND user_id=%s",(tenant,user))
            self._audit(conn,tenant,actor,user,action)
            return AccountStatus(*row)
