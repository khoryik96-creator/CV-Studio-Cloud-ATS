"""Operator-only installation of narrow workspace roles and grants.

Must target the marked dedicated online database. Role passwords are read
from distinct protected files. The initializer does not overwrite existing
credentials, create accounts, start a web service or dispatch AI.
"""
from hashlib import sha256
from psycopg import sql
from cloud.deploy.online_init import ROOT, BOOT, OWNER, DB, connect_as, read_secret
from cloud.deploy.online_workspace_schema import migration_plan
from cloud.deploy.workspace_roles import verify_service_role

ROLES = {
    "document": "cvcloud_document",
    "worker": "cvcloud_worker",
    "provider": "cvcloud_provider",
    "provider_reader": "cvcloud_provider_reader",
    "scheduler": "cvcloud_scheduler",
}
GRANT_FILE=ROOT/"cloud/deploy/workspace_data_grants.sql"

def install_grants(*, boot_connect, secrets, runtime_connect):
    if set(secrets)!=set(ROLES) or len(set(secrets.values()))!=len(ROLES):
        raise ValueError("Distinct workspace role secrets required")
    raw=GRANT_FILE.read_bytes()
    signature=sha256(raw).hexdigest()
    prefix,marker,body=raw.decode("utf-8").partition("BEGIN;\n")
    if not marker or not body.rstrip().endswith("\nCOMMIT;"):
        raise RuntimeError("Unexpected grant transaction wrapper")
    statement=prefix+body.rstrip().removesuffix("\nCOMMIT;")
    expected=[(name,digest) for name,digest,_ in migration_plan()]
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
            raise RuntimeError("Wrong dedicated bootstrap database")
        if conn.execute("SELECT to_regclass('cvcloud.online_workspace_migrations')").fetchone()[0] is None:
            raise RuntimeError("Workspace schema required")
        if conn.execute("SELECT name,signature FROM cvcloud.online_workspace_migrations ORDER BY name").fetchall()!=expected:
            raise RuntimeError("Unrecognized workspace migration history")
        if conn.execute("SELECT to_regclass('cvcloud.online_workspace_grants')").fetchone()[0] is not None:
            if conn.execute("SELECT signature FROM cvcloud.online_workspace_grants").fetchall()!=[(signature,)]:
                raise RuntimeError("Grant policy changed; explicit upgrade required")
        else:
            if conn.execute("SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)",(list(ROLES.values()),)).fetchone():
                raise RuntimeError("Refusing existing unmarked workspace roles")
            for service,role in ROLES.items():
                conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}")
                    .format(sql.Identifier(role),sql.Literal(secrets[service])))
                conn.execute(sql.SQL("GRANT CONNECT ON DATABASE cvcloud_online TO {}").format(sql.Identifier(role)))
            conn.execute("SET LOCAL ROLE cvcloud_schema_owner")
            conn.execute(statement,prepare=False)
            conn.execute("CREATE TABLE cvcloud.online_workspace_grants (signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_workspace_grants VALUES (%s)",(signature,))
    for service,role in ROLES.items():
        verify_service_role(lambda:runtime_connect(role,secrets[service]),service)

def main():
    try:
        boot=read_secret("CVCLOUD_BOOTSTRAP_PASSWORD_FILE")
        secrets={service:read_secret("CVCLOUD_"+service.upper()+"_PASSWORD_FILE") for service in ROLES}
        if boot in secrets.values():
            raise ValueError("Bootstrap password cannot be reused")
        install_grants(boot_connect=lambda:connect_as(BOOT,boot),secrets=secrets,runtime_connect=connect_as)
    except Exception:
        raise SystemExit("Workspace grants refused or failed; inspect isolated operator configuration.") from None
    print("Restricted workspace roles verified.")

if __name__=="__main__":
    main()
