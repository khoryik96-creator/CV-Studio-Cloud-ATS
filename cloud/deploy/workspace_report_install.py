"""Add report column grants without changing the signed foundation grants.

Operator-only, transactional and additive. No network or provider calls.
"""
from hashlib import sha256
from cloud.deploy.online_owner import operator_connection, verify_owner_database
from cloud.deploy.workspace_grant_install import GRANT_FILE as DATA_GRANTS
from cloud.deploy.workspace_admin_install import GRANT_FILE as ADMIN_GRANTS
from cloud.deploy.online_workspace_schema import migration_plan

STATEMENTS=(
    "GRANT UPDATE (report_options) ON cvcloud.jobs TO cvcloud_document",
    "GRANT UPDATE (report_result) ON cvcloud.jobs TO cvcloud_worker",
)
SIGNATURE=sha256("\n".join(STATEMENTS).encode()).hexdigest()

def install(connect=operator_connection):
    with connect() as conn:
        verify_owner_database(conn)
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        expected=[(name,digest) for name,digest,_ in migration_plan()]
        if conn.execute("SELECT name,signature FROM cvcloud.online_workspace_migrations ORDER BY name").fetchall()!=expected:
            raise RuntimeError("Unexpected workspace history")
        for table,source in (("online_workspace_grants",DATA_GRANTS),("online_admin_grants",ADMIN_GRANTS)):
            if conn.execute("SELECT signature FROM cvcloud."+table).fetchall()!=[(sha256(source.read_bytes()).hexdigest(),)]:
                raise RuntimeError("Unexpected grant history")
        exists=conn.execute("SELECT to_regclass('cvcloud.online_report_grants') IS NOT NULL").fetchone()[0]
        if exists:
            if conn.execute("SELECT signature FROM cvcloud.online_report_grants").fetchall()!=[(SIGNATURE,)]:
                raise RuntimeError("Report grants changed; explicit upgrade required")
        else:
            for statement in STATEMENTS:
                conn.execute(statement)
            conn.execute("CREATE TABLE cvcloud.online_report_grants (signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_report_grants VALUES (%s)",(SIGNATURE,))
        grants=conn.execute("""SELECT
            has_column_privilege('cvcloud_document','cvcloud.jobs','report_options','UPDATE'),
            has_column_privilege('cvcloud_document','cvcloud.jobs','report_result','UPDATE'),
            has_column_privilege('cvcloud_worker','cvcloud.jobs','report_options','UPDATE'),
            has_column_privilege('cvcloud_worker','cvcloud.jobs','report_result','UPDATE')""").fetchone()
        if grants!=(True,False,False,True):
            raise RuntimeError("Unexpected report column grants")

def main():
    try:
        install()
    except Exception:
        raise SystemExit("Report grant installation refused or failed.") from None
    print("Restricted report grants verified.")

if __name__=="__main__":
    main()
