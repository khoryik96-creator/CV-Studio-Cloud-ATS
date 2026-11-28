"""Public-host authentication foundation. No document services or live integrations.

This factory does not start a listener. The operator must provision a separate
database, restricted role, secret mount and verified reverse proxy first.
"""
from dataclasses import dataclass, field
from ipaddress import ip_address
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from cloud.app import create_app
from cloud.auth_postgres import PostgresAuthStore

HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

@dataclass(frozen=True)
class OnlineAuthConfig:
    origin: str
    proxy_ip: str
    password: str = field(repr=False)

def read_config(env=None):
    env = os.environ if env is None else env
    origin = env.get("CVCLOUD_PUBLIC_ORIGIN", "")
    try:
        parsed = urlsplit(origin)
        host = parsed.hostname or ""
        labels = host.split(".")
        if (len(host) > 253 or len(labels) < 2 or
                not all(HOST_LABEL.fullmatch(x) for x in labels) or
                labels[-1] in {"test", "localhost", "invalid", "example", "local"} or
                not labels[-1].isalpha() or origin != "https://" + host):
            raise ValueError()
        proxy = str(ip_address(env.get("CVCLOUD_TRUSTED_PROXY_IP", "")))
        if ip_address(proxy).is_unspecified or ip_address(proxy).is_multicast:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("Exact HTTPS public origin and single trusted proxy IP required") from None
    path = env.get("CVCLOUD_AUTH_PASSWORD_FILE", "")
    if not path or not Path(path).is_absolute():
        raise ValueError("Absolute mounted database password file required")
    password = Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    if not 24 <= len(password) <= 256 or any(c.isspace() or ord(c)<32 or ord(c)==127 for c in password):
        raise ValueError("Strong database role password required")
    return OnlineAuthConfig(origin, proxy, password)

class DedicatedAuthStore(PostgresAuthStore):
    def _lock_account(self, conn, account):
        return conn.execute("""SELECT credential_version,tenant_epoch
            FROM cvcloud.lock_auth_account(%s::uuid,%s::uuid,%s::text,%s::bigint,%s::bigint)""",
            (account.tenant_id,account.user_id,account.password_hash,
             account.credential_version,account.tenant_epoch)).fetchone()

def connection_factory(config):
    import psycopg
    def connect():
        # No arbitrary DSN, fixture DB, host networking, or superuser role.
        return psycopg.connect(host="online-db", port=5432, dbname="cvcloud_online",
            user="cvcloud_auth", password=config.password, connect_timeout=5,
            options="-c statement_timeout=5000 -c lock_timeout=3000")
    return connect

def verify_database(connect):
    with connect() as conn:
        row = conn.execute("""SELECT current_database(),current_user::text,session_user::text,
            NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication),
            NOT has_any_column_privilege(current_user,'cvcloud.users','UPDATE,INSERT'),
            NOT has_any_column_privilege(current_user,'cvcloud.tenants','UPDATE,INSERT'),
            NOT has_table_privilege(current_user,'cvcloud.users','DELETE,TRUNCATE'),
            NOT has_table_privilege(current_user,'cvcloud.tenants','DELETE,TRUNCATE'),
            has_function_privilege(current_user,'cvcloud.lock_auth_account(uuid,uuid,text,bigint,bigint)','EXECUTE')
            FROM pg_roles WHERE rolname=current_user""").fetchone()
        if row != ("cvcloud_online","cvcloud_auth","cvcloud_auth",True,True,True,True,True,True):
            raise RuntimeError("Dedicated authentication database/role verification failed")

class TrustedProxyOnly:
    """Trust exactly one immediate peer, with a single canonical client IP.

    The ingress must overwrite forwarding headers rather than append to them.
    The WSGI server must preserve the original peer and these two headers.
    """
    def __init__(self, app, proxy_ip):
        self.app, self.proxy_ip = app, ip_address(proxy_ip)

    def __call__(self, environ, start_response):
        try:
            peer = ip_address(environ.get("REMOTE_ADDR", ""))
            client = ip_address(environ.get("HTTP_X_FORWARDED_FOR", ""))
            if peer != self.proxy_ip or environ.get("HTTP_X_FORWARDED_PROTO") != "https":
                raise ValueError()
        except (TypeError, ValueError):
            start_response("403 Forbidden", [("Content-Type","text/plain"),("Cache-Control","no-store")])
            return [b"Forbidden"]
        clean = dict(environ)
        clean["REMOTE_ADDR"] = str(client)
        clean["wsgi.url_scheme"] = "https"
        for key in tuple(clean):
            if key.startswith("HTTP_X_FORWARDED_") or key == "HTTP_FORWARDED":
                del clean[key]
        return self.app(clean, start_response)

def build_online_auth(*, config, connect=None):
    if connect is None:
        connect = connection_factory(config)
    verify_database(connect)
    app = create_app(auth_store=DedicatedAuthStore(connect),public_origin=config.origin)
    app.wsgi_app = TrustedProxyOnly(app.wsgi_app, config.proxy_ip)
    return app
