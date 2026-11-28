"""Install reviewed additive enrollment policy, with no direct runtime grants."""
from hashlib import sha256
from cloud.deploy.online_init import ROOT
from cloud.deploy.online_owner import operator_connection,verify_owner_database
from cloud.deploy.workspace_report_install import SIGNATURE as REPORT_SIGNATURE

SCRIPT=ROOT/"cloud/deploy/workspace_staff_access.sql"

def install(connect=operator_connection):
    raw=SCRIPT.read_bytes()
    signature=sha256(raw).hexdigest()
    prefix,marker,body=raw.decode().partition("BEGIN;\n")
    if not marker or not body.rstrip().endswith("\nCOMMIT;"):
        raise RuntimeError("Unexpected staff policy transaction wrapper")
    with connect() as conn:
        verify_owner_database(conn)
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        if conn.execute("SELECT signature FROM cvcloud.online_report_grants").fetchall()!=[(REPORT_SIGNATURE,)]:
            raise RuntimeError("Verified report grants required")
        if conn.execute("SELECT to_regclass('cvcloud.online_staff_grants') IS NOT NULL").fetchone()[0]:
            if conn.execute("SELECT signature FROM cvcloud.online_staff_grants").fetchall()!=[(signature,)]:
                raise RuntimeError("Staff access policy changed; explicit review required")
        else:
            conn.execute(prefix+body.rstrip().removesuffix("\nCOMMIT;"),prepare=False)
            conn.execute("CREATE TABLE cvcloud.online_staff_grants(signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_staff_grants VALUES (%s)",(signature,))
        for role in ("cvcloud_worker","cvcloud_document","cvcloud_admin","cvcloud_provider","cvcloud_provider_reader","cvcloud_scheduler","cvcloud_auth"):
            row=conn.execute("""SELECT has_table_privilege(%s,'cvcloud.staff_enrollments','SELECT,INSERT,UPDATE,DELETE,TRUNCATE'),
                has_any_column_privilege(%s,'cvcloud.staff_enrollments','SELECT,INSERT,UPDATE'),
                has_function_privilege(%s,'cvcloud.redeem_staff_enrollment(text,text,text)','EXECUTE')""",(role,role,role)).fetchone()
            if row!=(False,False,role=="cvcloud_auth"):
                raise RuntimeError("Unexpected staff access grants")

if __name__=="__main__":
    try:
        install()
    except Exception:
        raise SystemExit("Staff access installation refused or failed.") from None
    print("Staff enrollment policy verified.")
