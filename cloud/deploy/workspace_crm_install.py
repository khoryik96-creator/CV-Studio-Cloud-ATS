"""Install additive CRM journal and narrowly scoped job column grants."""
from hashlib import sha256
from cloud.deploy.online_init import ROOT
from cloud.deploy.online_owner import operator_connection,verify_owner_database
from cloud.deploy.workspace_report_install import SIGNATURE as REPORT_SIGNATURE

SCRIPT=ROOT/"cloud/deploy/workspace_crm_journal.sql"

def install(connect=operator_connection):
    raw=SCRIPT.read_bytes()
    signature=sha256(raw).hexdigest()
    prefix,marker,body=raw.decode().partition("BEGIN;\n")
    if not marker or not body.rstrip().endswith("\nCOMMIT;"):
        raise RuntimeError("Unexpected CRM transaction wrapper")
    with connect() as conn:
        verify_owner_database(conn)
        conn.execute("SELECT pg_advisory_xact_lock(20261128,49)")
        if conn.execute("SELECT signature FROM cvcloud.online_report_grants").fetchall()!=[(REPORT_SIGNATURE,)]:
            raise RuntimeError("Verified report grants required")
        exists=conn.execute("SELECT to_regclass('cvcloud.online_crm_grants') IS NOT NULL").fetchone()[0]
        if exists:
            if conn.execute("SELECT signature FROM cvcloud.online_crm_grants").fetchall()!=[(signature,)]:
                raise RuntimeError("CRM policy changed; explicit review required")
        else:
            conn.execute(prefix+body.rstrip().removesuffix("\nCOMMIT;"),prepare=False)
            conn.execute("CREATE TABLE cvcloud.online_crm_grants (signature text PRIMARY KEY)")
            conn.execute("INSERT INTO cvcloud.online_crm_grants VALUES (%s)",(signature,))
        for role in ("cvcloud_worker","cvcloud_document","cvcloud_admin","cvcloud_provider","cvcloud_provider_reader","cvcloud_scheduler","cvcloud_auth"):
            row=conn.execute("""SELECT has_table_privilege(%s,'cvcloud.crm_attempts','SELECT,INSERT,UPDATE,DELETE,TRUNCATE'),
                has_any_column_privilege(%s,'cvcloud.crm_attempts','SELECT,INSERT,UPDATE'),
                has_function_privilege(%s,'cvcloud.record_crm_attempt(uuid,uuid,text,text)','EXECUTE')""",(role,role,role)).fetchone()
            if row!=(False,False,role=="cvcloud_worker"):
                raise RuntimeError("Unexpected CRM journal grants")
        row=conn.execute("""SELECT
            has_column_privilege('cvcloud_document','cvcloud.jobs','profile_confirmation','UPDATE'),
            has_column_privilege('cvcloud_document','cvcloud.jobs','profile_started_at','UPDATE'),
            has_column_privilege('cvcloud_document','cvcloud.jobs','profile_result','UPDATE'),
            has_column_privilege('cvcloud_worker','cvcloud.jobs','profile_confirmation','UPDATE'),
            has_column_privilege('cvcloud_worker','cvcloud.jobs','profile_started_at','UPDATE'),
            has_column_privilege('cvcloud_worker','cvcloud.jobs','profile_result','UPDATE')""").fetchone()
        if row!=(True,False,False,False,True,True):
            raise RuntimeError("Unexpected CRM job grants")

if __name__=="__main__":
    try:
        install()
    except Exception:
        raise SystemExit("CRM journal installation refused or failed.") from None
    print("CRM attempt journal and restricted grants verified.")
