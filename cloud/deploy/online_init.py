"""Initialize an isolated auth database once; never migrate existing data."""
import hashlib
import os
from pathlib import Path
import re
from cloud.deploy.online_auth import verify_database
from cloud.deploy.online_owner import verify_owner_database

ROOT=Path(__file__).resolve().parents[2]
SCRIPTS=("cloud/migrations/001_auth.sql","cloud/migrations/004_auth_epoch.sql","cloud/deploy/online_auth_grants.sql")
DB="cvcloud_online"
BOOT="cvcloud_bootstrap"
OWNER="cvcloud_schema_owner"
AUTH="cvcloud_auth"

def read_secret(name):
    path=os.environ.get(name,"")
    if not path or not Path(path).is_absolute():
        raise ValueError("Absolute secret file required")
    value=Path(path).read_text(encoding="utf-8").rstrip("\r\n")
    if not re.fullmatch("[0-9a-f]{64}",value):
        raise ValueError("Generate a unique 32-byte hexadecimal secret")
    return value

def connect_as(role,password):
    import psycopg
    return psycopg.connect(host="online-db",port=5432,dbname=DB,user=role,password=password,
        connect_timeout=5,options="-c statement_timeout=15000 -c lock_timeout=5000")

def scripts():
    statements=[]
    digest=hashlib.sha256()
    for name in SCRIPTS:
        raw=(ROOT/name).read_bytes()
        digest.update(name.encode()+b"\0"+raw+b"\0")
        text=raw.decode("utf-8")
        before,marker,body=text.partition("BEGIN;\n")
        if not marker or not body.rstrip().endswith("\nCOMMIT;"):
            raise ValueError("Unexpected migration transaction wrapper")
        statements.append(before+body.rstrip().removesuffix("\nCOMMIT;"))
    return digest.hexdigest(),statements

def initialize():
    from psycopg import sql
    boot,owner,auth=(read_secret(name) for name in ("CVCLOUD_BOOTSTRAP_PASSWORD_FILE",
        "CVCLOUD_SCHEMA_PASSWORD_FILE","CVCLOUD_AUTH_PASSWORD_FILE"))
    if len({boot,owner,auth})!=3:
        raise ValueError("Database role secrets must be distinct")
    signature,statements=scripts()
    with connect_as(BOOT,boot) as conn:
        # Never include credential-bearing statements in server error logging.
        conn.execute("SET LOCAL log_statement='none'")
        conn.execute("SET LOCAL log_min_error_statement='panic'")
        conn.execute("SET LOCAL log_parameter_max_length_on_error=0")
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        identity=conn.execute("""SELECT current_database(),current_user::text,session_user::text,
            (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
            to_regclass('public.cvcloud_fixture_marker') IS NULL,
            (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)""").fetchone()
        if identity!=(DB,BOOT,BOOT,BOOT,True,True):
            raise RuntimeError("Wrong dedicated bootstrap database")
        existing=conn.execute("SELECT to_regnamespace('cvcloud') IS NOT NULL").fetchone()[0]
        if existing:
            if conn.execute("SELECT to_regclass('cvcloud.online_auth_marker')").fetchone()[0] is None:
                raise RuntimeError("Refusing existing unmarked schema")
            if conn.execute("SELECT signature FROM cvcloud.online_auth_marker").fetchall()!=[(signature,)]:
                raise RuntimeError("Schema signature changed; explicit reviewed migration required")
        else:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname IN (%s,%s)",(OWNER,AUTH)).fetchone():
                raise RuntimeError("Refusing existing database roles")
            # No other application schema or user table may exist in a fresh DB.
            if conn.execute("""SELECT 1 FROM pg_namespace WHERE nspname NOT IN
                ('public','pg_catalog','information_schema','pg_toast') AND nspname NOT LIKE 'pg_temp_%'
                AND nspname NOT LIKE 'pg_toast_temp_%' LIMIT 1""").fetchone() or conn.execute(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' LIMIT 1").fetchone():
                raise RuntimeError("Refusing nonempty database")
            for role,password in ((OWNER,owner),(AUTH,auth)):
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}")
                    .format(sql.Identifier(role),sql.Literal(password)))
            conn.execute("REVOKE ALL ON DATABASE cvcloud_online FROM PUBLIC")
            conn.execute("GRANT CONNECT,CREATE ON DATABASE cvcloud_online TO cvcloud_schema_owner")
            conn.execute("GRANT CONNECT ON DATABASE cvcloud_online TO cvcloud_auth")
            conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
            conn.execute("GRANT USAGE ON SCHEMA public TO cvcloud_schema_owner")
            conn.execute("SET LOCAL ROLE cvcloud_schema_owner")
            for statement in statements:
                conn.execute(statement,prepare=False)
            conn.execute("CREATE TABLE cvcloud.online_auth_marker (signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_auth_marker VALUES (%s)",(signature,))
    # Validate supplied credentials on every run. Never silently reset them.
    with connect_as(OWNER,owner) as conn:
        verify_owner_database(conn)
    verify_database(lambda:connect_as(AUTH,auth))

def main():
    try:
        initialize()
    except Exception:
        raise SystemExit("Online initialization refused or failed; inspect isolated configuration without printing secrets.") from None
    print("Dedicated authentication schema verified.")

if __name__=="__main__":
    main()
