"""Operator-only install of function-only account administration.

This module requires the merged workspace foundation. It never changes
existing role passwords, starts services, creates users or grants table access.
"""
from hashlib import sha256
from pathlib import Path
import re
from cloud.deploy.online_init import ROOT, BOOT, DB, connect_as, read_secret

ROLE="cvcloud_admin"
GRANT_FILE=ROOT/"cloud/deploy/workspace_admin_grants.sql"
FUNCTIONS=("admin_list_accounts()","admin_change_account(uuid,bigint,text,text,uuid)","admin_usage_snapshot()")
BLOCKED_TABLES=("users","tenants","sessions","account_challenges","account_audit",
    "provider_config","documents","jobs","ai_budgets","ai_reservations")

def verify_admin_role(connect):
    with connect() as conn:
        row=conn.execute("""SELECT current_database(),current_user::text,session_user::text,
            NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication OR rolinherit),
            NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=r.oid),
            NOT has_schema_privilege(current_user,'cvcloud','CREATE'),
            NOT has_database_privilege(current_user,current_database(),'CREATE'),
            NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
               WHERE n.nspname='cvcloud' AND c.relowner=r.oid)
            FROM pg_roles r WHERE rolname=current_user""").fetchone()
        if row!=(DB,ROLE,ROLE,True,True,True,True,True):
            raise RuntimeError("Invalid restricted admin identity")
        for table in BLOCKED_TABLES:
            row=conn.execute("""SELECT has_table_privilege(current_user,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),
                has_any_column_privilege(current_user,%s,'SELECT,INSERT,UPDATE,REFERENCES')""",
                ("cvcloud."+table,"cvcloud."+table)).fetchone()
            if row!=(False,False):
                raise RuntimeError("Admin has prohibited direct table access")
        for function in FUNCTIONS:
            if conn.execute("SELECT has_function_privilege(current_user,%s,'EXECUTE')",
                ("cvcloud."+function,)).fetchone()!=(True,):
                raise RuntimeError("Missing restricted admin function")
        if conn.execute("SELECT has_function_privilege(current_user,'cvcloud.admin_actor_lock()','EXECUTE')").fetchone()!=(False,):
            raise RuntimeError("Internal actor helper must not be directly callable")

def install(*,boot_connect,password,admin_connect):
    from psycopg import sql
    if not isinstance(password,str) or not re.fullmatch("[0-9a-f]{64}",password):
        raise ValueError("Distinct 32-byte role password required")
    raw=GRANT_FILE.read_bytes()
    signature=sha256(raw).hexdigest()
    prefix,marker,body=raw.decode("utf-8").partition("BEGIN;\n")
    if not marker or not body.rstrip().endswith("\nCOMMIT;"):
        raise RuntimeError("Unexpected grant transaction wrapper")
    statement=prefix+body.rstrip().removesuffix("\nCOMMIT;")
    with boot_connect() as conn:
        conn.execute("SET LOCAL log_statement='none'")
        conn.execute("SET LOCAL log_min_error_statement='panic'")
        conn.execute("SET LOCAL log_parameter_max_length_on_error=0")
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        identity=conn.execute("""SELECT current_database(),current_user::text,session_user::text,
            (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
            to_regclass('public.cvcloud_fixture_marker') IS NULL,
            (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)""").fetchone()
        if identity!=(DB,BOOT,BOOT,BOOT,True,True):
            raise RuntimeError("Wrong dedicated database")
        # The exact workspace migration/grant signatures must be present.
        from cloud.deploy.online_workspace_schema import migration_plan
        from cloud.deploy.workspace_grant_install import GRANT_FILE as DATA_GRANTS
        expected=[(name,digest) for name,digest,_ in migration_plan()]
        if conn.execute("SELECT name,signature FROM cvcloud.online_workspace_migrations ORDER BY name").fetchall()!=expected:
            raise RuntimeError("Unexpected workspace schema history")
        if conn.execute("SELECT signature FROM cvcloud.online_workspace_grants").fetchall()!=[(sha256(DATA_GRANTS.read_bytes()).hexdigest(),)]:
            raise RuntimeError("Unexpected workspace grant history")
        if conn.execute("SELECT to_regclass('cvcloud.online_admin_grants')").fetchone()[0] is not None:
            if conn.execute("SELECT signature FROM cvcloud.online_admin_grants").fetchall()!=[(signature,)]:
                raise RuntimeError("Admin grants changed; explicit upgrade required")
        else:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s",(ROLE,)).fetchone():
                raise RuntimeError("Unmarked admin role already exists")
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}")
                .format(sql.Identifier(ROLE),sql.Literal(password)))
            conn.execute("GRANT CONNECT ON DATABASE cvcloud_online TO cvcloud_admin")
            conn.execute("SET LOCAL ROLE cvcloud_schema_owner")
            conn.execute(statement,prepare=False)
            conn.execute("CREATE TABLE cvcloud.online_admin_grants (signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_admin_grants VALUES (%s)",(signature,))
    verify_admin_role(admin_connect)

def main():
    try:
        boot=read_secret("CVCLOUD_BOOTSTRAP_PASSWORD_FILE")
        password=read_secret("CVCLOUD_ADMIN_PASSWORD_FILE")
        if boot==password:
            raise ValueError("Distinct role password required")
        install(boot_connect=lambda:connect_as(BOOT,boot),password=password,
            admin_connect=lambda:connect_as(ROLE,password))
    except Exception:
        raise SystemExit("Admin grant installation refused or failed.") from None
    print("Restricted account administration functions verified.")

if __name__=="__main__":
    main()
