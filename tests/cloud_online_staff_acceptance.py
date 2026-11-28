"""Exercise actual restricted-role enrollment against disposable PostgreSQL."""
from cloud.auth import Auth,digest
from cloud.deploy.online_auth import DedicatedAuthStore
from cloud.deploy.workspace_staff_access import issue_staff,redeem_staff
from cloud.deploy.workspace_staff_install import install

def verify_staff(test,*,owner_connect,auth_connect,tenant_id,other_tenant):
    import psycopg
    install(owner_connect)
    install(owner_connect)
    auth=Auth(DedicatedAuthStore(auth_connect))
    with test.assertRaises(ValueError):
        issue_staff(owner_connect,tenant="one",email="owner@example.test")
    previous=issue_staff(owner_connect,tenant="one",email="staff@example.test")
    token=issue_staff(owner_connect,tenant="one",email="staff@example.test")
    test.assertNotEqual(previous,token)
    with auth_connect() as conn:
        with test.assertRaises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM cvcloud.staff_enrollments")
        conn.rollback()
    test.assertIsNone(redeem_staff(auth,previous,"192.0.2.41"))
    raw=redeem_staff(auth,token,"192.0.2.41")
    test.assertIsNotNone(raw)
    p=auth.principal(raw)
    test.assertEqual((p.tenant_id,p.role),(tenant_id,"recruiter"))
    test.assertNotEqual(p.tenant_id,other_tenant)
    test.assertIsNone(redeem_staff(auth,token,"192.0.2.41"))
    with owner_connect() as conn:
        row=conn.execute("""SELECT expires_at>clock_timestamp()+interval '89 days',
            expires_at<=clock_timestamp()+interval '90 days' FROM cvcloud.sessions
            WHERE token_digest=%s""",(digest(raw),)).fetchone()
        test.assertEqual(row,(True,True))
    expired=issue_staff(owner_connect,tenant="one",email="staff@example.test")
    with owner_connect() as conn:
        conn.execute("UPDATE cvcloud.staff_enrollments SET expires_at=clock_timestamp()-interval '1 second' WHERE token_digest=%s",(digest(expired),))
    test.assertIsNone(redeem_staff(auth,expired,"192.0.2.41"))
    stale=issue_staff(owner_connect,tenant="one",email="staff@example.test")
    with owner_connect() as conn:
        conn.execute("UPDATE cvcloud.users SET credential_version=credential_version+1 WHERE tenant_id=%s AND id=%s",(p.tenant_id,p.user_id))
    test.assertIsNone(auth.principal(raw))
    test.assertIsNone(redeem_staff(auth,stale,"192.0.2.41"))
    with owner_connect() as conn:
        conn.execute("UPDATE cvcloud.users SET active=false WHERE tenant_id=%s AND id=%s",(p.tenant_id,p.user_id))
    with test.assertRaises(ValueError):
        issue_staff(owner_connect,tenant="one",email="staff@example.test")
