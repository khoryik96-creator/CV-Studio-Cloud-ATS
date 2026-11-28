"""Startup checks for the online workspace. No schema changes or credential logging.

Separate role names alone do not prove a safe deployment. These checks are a
minimum gate; database-level grants and RLS must also pass disposable integration
tests before this assembly is connected to an entrypoint.
"""
from cloud.auth import Principal, ROLES
from cloud.documents_jobs import uid

ROLES_BY_SERVICE = {
    "document": "cvcloud_document",
    "admin": "cvcloud_admin",
    "provider": "cvcloud_provider",
    "provider_reader": "cvcloud_provider_reader",
    "worker": "cvcloud_worker",
    "scheduler": "cvcloud_scheduler",
}

def verify_service_role(connect, service):
    expected = ROLES_BY_SERVICE[service]
    with connect() as conn:
        identity = conn.execute("""SELECT current_database(),current_user::text,session_user::text,
            NOT (rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication),
            NOT EXISTS (SELECT 1 FROM pg_auth_members WHERE member=r.oid),
            NOT has_schema_privilege(current_user,'cvcloud','CREATE'),
            NOT has_database_privilege(current_user,current_database(),'CREATE'),
            NOT has_column_privilege(current_user,'cvcloud.users','password_hash','SELECT'),
            NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname='cvcloud' AND c.relowner=r.oid)
            FROM pg_roles r WHERE rolname=current_user""").fetchone()
        if identity != ("cvcloud_online", expected, expected, True, True, True, True, True, True):
            raise RuntimeError("Online workspace role identity or privilege verification failed")
        # No workspace role may insert/delete sessions or change tenant records.
        # Admin can revoke sessions but cannot mint an authentication session.
        blocked = conn.execute("""SELECT
            has_table_privilege(current_user,'cvcloud.sessions','INSERT'),
            has_any_column_privilege(current_user,'cvcloud.sessions','UPDATE'),
            has_table_privilege(current_user,'cvcloud.tenants','INSERT,DELETE,TRUNCATE'),
            has_any_column_privilege(current_user,'cvcloud.tenants','UPDATE')""").fetchone()
        # Existing account/provider/document services still have SQL row-lock
        # dependencies; those need narrow lock helpers instead of UPDATE grants.
        if blocked != (False,False,False,False):
            raise RuntimeError("Online workspace role has prohibited privileges")
        if service != "admin":
            forbidden = conn.execute("""SELECT
                has_column_privilege(current_user,'cvcloud.users','password_hash','UPDATE,INSERT'),
                has_column_privilege(current_user,'cvcloud.users','role','UPDATE'),
                has_column_privilege(current_user,'cvcloud.users','active','UPDATE'),
                has_table_privilege(current_user,'cvcloud.sessions','DELETE')""").fetchone()
            if forbidden != (False,False,False,False):
                raise RuntimeError("Online workspace role may mutate credentials")
        if service != "provider_reader":
            secret = conn.execute("""SELECT
                has_column_privilege(current_user,'cvcloud.provider_config','ciphertext','SELECT'),
                has_column_privilege(current_user,'cvcloud.provider_config','nonce','SELECT')""").fetchone()
            if secret != (False,False):
                raise RuntimeError("Online workspace role may read provider secrets")
        if service == "provider_reader":
            grants = conn.execute("""SELECT
                has_column_privilege(current_user,'cvcloud.provider_config','ciphertext','SELECT'),
                has_any_column_privilege(current_user,'cvcloud.provider_config','INSERT,UPDATE'),
                has_table_privilege(current_user,'cvcloud.provider_config','DELETE,TRUNCATE')""").fetchone()
            if grants != (True,False,False):
                raise RuntimeError("Provider reader must be read-only")
        if service == "scheduler":
            privileges = conn.execute("""SELECT
                has_table_privilege(current_user,'cvcloud.documents','SELECT,INSERT,UPDATE,DELETE,TRUNCATE'),
                has_table_privilege(current_user,'cvcloud.jobs','SELECT,INSERT,UPDATE,DELETE,TRUNCATE'),
                has_function_privilege(current_user,'cvcloud.active_worker_roster()','EXECUTE')""").fetchone()
            if privileges != (False,False,True):
                raise RuntimeError("Scheduler must only receive the bounded roster")

def discover_roster(connect):
    """Read identities only from a future restricted scheduler function.

    The function must return at most 101 active rows, deterministically sorted
    by tenant/user; 101 is an explicit overflow signal. Never silently drop
    accounts. Existing WorkerRuntime supports up to 100 principals per process.
    """
    verify_service_role(connect, "scheduler")
    with connect() as conn:
        rows = conn.execute("SELECT tenant_id,user_id,role FROM cvcloud.active_worker_roster() LIMIT 101").fetchall()
    if len(rows)>100:
        raise RuntimeError("Worker roster capacity exceeded; partitioning required")
    result=[]
    seen=set()
    for tenant,user,role in rows:
        key=(uid(tenant),uid(user))
        if key in seen or role not in ROLES:
            raise RuntimeError("Invalid worker roster")
        seen.add(key)
        # Worker has no browser token; it uses only trusted server identities.
        result.append(Principal(*key,role,""))
    return tuple(result)
