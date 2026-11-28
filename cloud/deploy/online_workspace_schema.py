"""Explicit, transactional extension of the marked auth-only online database.

No runtime grants, credentials, startup or public deployment are enabled here.
An operator invokes this only after the integrated workspace has been reviewed.
"""
from hashlib import sha256
from cloud.deploy.online_init import ROOT, SCRIPTS as AUTH_SCRIPTS, scripts as auth_scripts
from cloud.deploy.online_owner import operator_connection, verify_owner_database

WORKSPACE_SCRIPTS = (
    "cloud/migrations/002_documents_jobs.sql",
    "cloud/migrations/003_ai_budget.sql",
    "cloud/migrations/005_job_outputs.sql",
    "cloud/migrations/006_job_options.sql",
    "cloud/migrations/007_provider_config.sql",
    "cloud/migrations/008_account_admin.sql",
    "cloud/migrations/009_history_indexes.sql",
    "cloud/migrations/010_account_onboarding.sql",
    "cloud/migrations/011_scoring_jobs.sql",
    "cloud/migrations/012_document_reports.sql",
    "cloud/migrations/013_create_profile.sql",
)
AUTH_TABLES = {"tenants", "users", "sessions", "login_attempts", "online_auth_marker"}

def migration_plan(root=ROOT):
    expected = {name for name in AUTH_SCRIPTS + WORKSPACE_SCRIPTS if name.startswith("cloud/migrations/")}
    actual = {p.relative_to(root).as_posix() for p in (root/"cloud/migrations").glob("*.sql")}
    if actual != expected:
        raise RuntimeError("Unexpected migration set; explicit review required")
    plan=[]
    for name in WORKSPACE_SCRIPTS:
        raw=(root/name).read_bytes()
        prefix,marker,body=raw.decode("utf-8").partition("BEGIN;\n")
        if not marker or not body.rstrip().endswith("\nCOMMIT;"):
            raise RuntimeError("Unexpected migration transaction wrapper")
        plan.append((name,sha256(raw).hexdigest(),prefix+body.rstrip().removesuffix("\nCOMMIT;")))
    return tuple(plan)

def apply_workspace_schema(connect=operator_connection):
    plan=migration_plan()
    expected_auth,_=auth_scripts()
    with connect() as conn:
        verify_owner_database(conn)
        conn.execute("SET LOCAL statement_timeout='30s'")
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        if conn.execute("SELECT signature FROM cvcloud.online_auth_marker").fetchall()!=[(expected_auth,)]:
            raise RuntimeError("Unrecognized auth schema")
        existing=conn.execute("SELECT to_regclass('cvcloud.online_workspace_migrations') IS NOT NULL").fetchone()[0]
        expected=[(name,digest) for name,digest,_ in plan]
        if existing:
            applied=conn.execute("SELECT name,signature FROM cvcloud.online_workspace_migrations ORDER BY name").fetchall()
            if applied!=expected:
                raise RuntimeError("Workspace migration history differs; explicit review required")
            return False
        tables={r[0] for r in conn.execute("""SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='cvcloud' AND c.relkind IN ('r','p','v','m','f')""").fetchall()}
        if tables!=AUTH_TABLES:
            raise RuntimeError("Refusing a partially initialized or unknown workspace")
        conn.execute("""CREATE TABLE cvcloud.online_workspace_migrations (
            name text PRIMARY KEY, signature text NOT NULL CHECK (signature ~ '^[a-f0-9]{64}$'),
            applied_at timestamptz NOT NULL DEFAULT clock_timestamp())""")
        for name,digest,statement in plan:
            conn.execute(statement,prepare=False)
            conn.execute("INSERT INTO cvcloud.online_workspace_migrations (name,signature) VALUES (%s,%s)",(name,digest))
        # Scheduler function exposes active identity/role only, never auth
        # password hashes, session tokens, or document data. Restricted grant
        # is a separate step; PUBLIC access is revoked in this transaction.
        conn.execute("""CREATE FUNCTION cvcloud.active_worker_roster()
            RETURNS TABLE(tenant_id uuid,user_id uuid,role text)
            LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog AS $roster$
            SELECT u.tenant_id,u.id,u.role FROM cvcloud.users u
            JOIN cvcloud.tenants t ON t.id=u.tenant_id
            WHERE u.active AND t.active ORDER BY u.tenant_id,u.id LIMIT 101
            $roster$""")
        conn.execute("REVOKE ALL ON FUNCTION cvcloud.active_worker_roster() FROM PUBLIC")
    return True

def main():
    try:
        applied=apply_workspace_schema()
    except Exception:
        raise SystemExit("Workspace migration refused or failed; inspect isolated operator configuration.") from None
    print("Workspace schema applied." if applied else "Workspace migration history verified.")

if __name__=="__main__":
    main()
