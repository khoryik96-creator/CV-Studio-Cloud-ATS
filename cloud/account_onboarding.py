"""Internal one-time invitation/reset service, not an HTTP or mail endpoint.

Trusted composition must isolate authentication database credentials, securely
deliver tokens, redact request bodies and rate-limit redemption before exposure.
Only a digest is persisted; raw tokens are never included in audit events.
"""
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
import secrets
from uuid import uuid4
from cloud.auth import TOKEN,digest,password_hash
from cloud.account_admin import AccountAdmin,AccountAdminError,_email,_allowed,_revision,_hash
from cloud.documents_jobs import uid

@dataclass(frozen=True,repr=False)
class Challenge:
    user_id: str
    token: str
    expires_at: datetime

class AccountOnboarding:
    def __init__(self,repository,*,clock=lambda:datetime.now(timezone.utc)):
        self.repository=repository
        self.admin=AccountAdmin(repository)
        self.clock=clock

    @staticmethod
    def _issue(conn,tenant,user,purpose,version,epoch,expires):
        raw=secrets.token_urlsafe(32)
        conn.execute("""INSERT INTO cvcloud.account_challenges
            (tenant_id,user_id,token_digest,purpose,credential_version,tenant_epoch,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id,user_id) DO UPDATE SET
            token_digest=EXCLUDED.token_digest,purpose=EXCLUDED.purpose,
            credential_version=EXCLUDED.credential_version,tenant_epoch=EXCLUDED.tenant_epoch,
            expires_at=EXCLUDED.expires_at""",(tenant,user,digest(raw),purpose,version,epoch,expires))
        return Challenge(user,raw,expires)

    def invite(self,principal,*,email,role):
        email=_email(email)
        with self.admin._scope(principal) as (conn,tenant,actor,actor_role):
            if not _allowed(actor_role,role):
                raise AccountAdminError("account_admin_denied")
            count=conn.execute("SELECT count(*) FROM cvcloud.users WHERE tenant_id=%s",(tenant,)).fetchone()[0]
            if count>=100:
                raise AccountAdminError("account_limit_exceeded")
            user=str(uuid4())
            # No one knows the placeholder password; account is inactive
            # until the recipient chooses their own password.
            row=conn.execute("""INSERT INTO cvcloud.users
                (tenant_id,id,email_normalized,password_hash,role,active)
                VALUES (%s,%s,%s,%s,%s,false) ON CONFLICT DO NOTHING
                RETURNING credential_version""",(tenant,user,email,password_hash(secrets.token_urlsafe(32)),role)).fetchone()
            if not row:
                raise AccountAdminError("account_conflict")
            epoch=conn.execute("SELECT auth_epoch FROM cvcloud.tenants WHERE id=%s",(tenant,)).fetchone()[0]
            result=self._issue(conn,tenant,user,"invite",row[0],epoch,self.clock()+timedelta(hours=24))
            self.admin._audit(conn,tenant,actor,user,"create")
            return result

    def reissue_invitation(self,principal,*,user_id,expected_revision):
        """Replace a pending invitation, including expired ones, never a suspension."""
        user,expected=uid(user_id),_revision(expected_revision)
        with self.admin._scope(principal) as (conn,tenant,actor,actor_role):
            row=conn.execute("""SELECT role,active,credential_version FROM cvcloud.users
                WHERE tenant_id=%s AND id=%s FOR UPDATE""",(tenant,user)).fetchone()
            if user==actor or not row or row[1] or not _allowed(actor_role,row[0]):
                raise AccountAdminError("account_admin_denied")
            if row[2]!=expected:
                raise AccountAdminError("account_conflict")
            old=conn.execute("""SELECT purpose,credential_version FROM cvcloud.account_challenges
                WHERE tenant_id=%s AND user_id=%s FOR UPDATE""",(tenant,user)).fetchone()
            if not old or old[0]!="invite" or old[1]!=expected:
                raise AccountAdminError("account_admin_denied")
            version=conn.execute("""UPDATE cvcloud.users SET credential_version=credential_version+1
                WHERE tenant_id=%s AND id=%s RETURNING credential_version""",(tenant,user)).fetchone()[0]
            epoch=conn.execute("SELECT auth_epoch FROM cvcloud.tenants WHERE id=%s",(tenant,)).fetchone()[0]
            result=self._issue(conn,tenant,user,"invite",version,epoch,self.clock()+timedelta(hours=24))
            self.admin._audit(conn,tenant,actor,user,"invite_reissue")
            return result

    def reset(self,principal,*,user_id,expected_revision):
        user,expected=uid(user_id),_revision(expected_revision)
        with self.admin._scope(principal) as (conn,tenant,actor,actor_role):
            if user==actor:
                raise AccountAdminError("account_admin_denied")
            row=conn.execute("""SELECT role,active,credential_version FROM cvcloud.users
                WHERE tenant_id=%s AND id=%s FOR UPDATE""",(tenant,user)).fetchone()
            if not row or not row[1] or not _allowed(actor_role,row[0]):
                raise AccountAdminError("account_admin_denied")
            if row[2]!=expected:
                raise AccountAdminError("account_conflict")
            # Immediately invalidate the old password and every login.
            version=conn.execute("""UPDATE cvcloud.users SET password_hash=%s
                WHERE tenant_id=%s AND id=%s RETURNING credential_version""",
                (password_hash(secrets.token_urlsafe(32)),tenant,user)).fetchone()[0]
            conn.execute("DELETE FROM cvcloud.sessions WHERE tenant_id=%s AND user_id=%s",(tenant,user))
            epoch=conn.execute("SELECT auth_epoch FROM cvcloud.tenants WHERE id=%s",(tenant,)).fetchone()[0]
            result=self._issue(conn,tenant,user,"reset",version,epoch,self.clock()+timedelta(hours=1))
            self.admin._audit(conn,tenant,actor,user,"password_reset")
            return result

    def redeem(self,token,password):
        """Consume once; no session issued automatically. False is generic."""
        if not isinstance(token,str) or not TOKEN.fullmatch(token):
            return False
        hashed_token=digest(token)
        # Read candidate identity without locking, then lock tenant, user and
        # challenge in the same order used by administrative issuance.
        with self.repository.connect() as conn:
            hint=conn.execute("""SELECT tenant_id,user_id FROM cvcloud.account_challenges
                WHERE token_digest=%s AND expires_at>%s""",(hashed_token,self.clock())).fetchone()
            if not hint:
                return False
            tenant,user=hint
            t=conn.execute("SELECT active,auth_epoch FROM cvcloud.tenants WHERE id=%s FOR UPDATE",(tenant,)).fetchone()
            u=conn.execute("""SELECT active,credential_version FROM cvcloud.users
                WHERE tenant_id=%s AND id=%s FOR UPDATE""",(tenant,user)).fetchone()
            c=conn.execute("""SELECT purpose,credential_version,tenant_epoch,expires_at
                FROM cvcloud.account_challenges WHERE tenant_id=%s AND user_id=%s
                AND token_digest=%s FOR UPDATE""",(tenant,user,hashed_token)).fetchone()
            if not t or not t[0] or not u or not c or c[3]<=self.clock() or c[1]!=u[1] or c[2]!=t[1]:
                return False
            if (c[0]=="invite" and u[0]) or (c[0]=="reset" and not u[0]):
                return False
            hashed=_hash(password)
            conn.execute("""UPDATE cvcloud.users SET password_hash=%s,active=true
                WHERE tenant_id=%s AND id=%s""",(hashed,tenant,user))
            conn.execute("DELETE FROM cvcloud.sessions WHERE tenant_id=%s AND user_id=%s",(tenant,user))
            conn.execute("DELETE FROM cvcloud.account_challenges WHERE tenant_id=%s AND user_id=%s",(tenant,user))
            return True
