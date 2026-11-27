"""PostgreSQL auth store; connection factory must supply a fresh transaction context.
No global connection, no implicit schema changes, no candidate document access.
"""
from datetime import timedelta
from cloud.auth import Account, Principal

class PostgresAuthStore:
    def __init__(self, connect):
        self.connect = connect

    def consume_attempt(self, key, now):
        window = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)
        with self.connect() as conn:
            row = conn.execute(
                """INSERT INTO cvcloud.login_attempts (bucket, window_start, attempts)
                   VALUES (%s, %s, 1)
                   ON CONFLICT (bucket, window_start) DO UPDATE
                   SET attempts = LEAST(cvcloud.login_attempts.attempts + 1, 11)
                   RETURNING attempts""", (key, window)).fetchone()
        return bool(row and row[0] <= 10)

    def find_account(self, tenant, email):
        with self.connect() as conn:
            row = conn.execute(
                """SELECT u.tenant_id::text,u.id::text,u.role,u.password_hash,u.active AND t.active,u.credential_version,t.auth_epoch
                   FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                   WHERE t.slug=%s AND u.email_normalized=%s""", (tenant, email)).fetchone()
        return Account(*row) if row else None

    def create_session(self, digest, csrf, account, expires):
        with self.connect() as conn:
            # The credential version is rechecked in the same transaction.
            # Serialize against password changes and tenant disable/enable, and
            # refuse credentials checked before either version changed.
            current = conn.execute("""SELECT u.credential_version,t.auth_epoch
                FROM cvcloud.users u JOIN cvcloud.tenants t ON t.id=u.tenant_id
                WHERE u.tenant_id=%s AND u.id=%s AND u.password_hash=%s
                AND u.credential_version=%s AND t.auth_epoch=%s AND u.active AND t.active
                FOR SHARE OF u,t""",(account.tenant_id,account.user_id,account.password_hash,
                account.credential_version,account.tenant_epoch)).fetchone()
            if not current:
                return False
            row = conn.execute("""INSERT INTO cvcloud.sessions
                (token_digest,csrf_token,tenant_id,user_id,expires_at,credential_version,tenant_epoch)
                VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING token_digest""",
                (digest,csrf,account.tenant_id,account.user_id,expires,*current)).fetchone()
        return row is not None

    def get_session(self, digest, now):
        with self.connect() as conn:
            row = conn.execute(
                """SELECT u.tenant_id::text,u.id::text,u.role,s.csrf_token
                   FROM cvcloud.sessions s JOIN cvcloud.users u ON (u.tenant_id,u.id)=(s.tenant_id,s.user_id)
                   JOIN cvcloud.tenants t ON t.id=u.tenant_id
                   WHERE s.token_digest=%s AND s.expires_at>%s AND u.active AND t.active AND s.credential_version=u.credential_version AND s.tenant_epoch=t.auth_epoch""",
                (digest, now)).fetchone()
        return Principal(*row) if row else None

    def delete_session(self, digest):
        with self.connect() as conn:
            conn.execute("DELETE FROM cvcloud.sessions WHERE token_digest=%s", (digest,))

    def purge_expired(self, now):
        with self.connect() as conn:
            conn.execute("DELETE FROM cvcloud.sessions WHERE expires_at<=%s", (now,))
            conn.execute("DELETE FROM cvcloud.login_attempts WHERE window_start<%s", (now-timedelta(hours=1),))
