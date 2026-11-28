"""Exercise actual restricted-role enrollment against disposable PostgreSQL."""
from cloud.auth import Auth,digest
from cloud.deploy.online_auth import DedicatedAuthStore
from cloud.deploy.workspace_staff_access import issue_staff,redeem_staff
from cloud.deploy.workspace_staff_install import install

def verify_staff(test,*,owner_connect,auth_connect,tenant_id,other_tenant):
    import psycopg
    from cloud.app import COOKIE, create_app
    from cloud.deploy.workspace_staff_web import register_staff_access, verify_staff_database
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
    origin = "https://cv.example.test"
    verify_staff_database(auth_connect)
    app = create_app(auth_store=auth.store, public_origin=origin)
    register_staff_access(app, public_origin=origin)
    browser = app.test_client()
    response = browser.get("/staff/enroll", base_url=origin)
    test.assertEqual(response.status_code, 200)
    test.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
    script = browser.get("/staff/enroll.js", base_url=origin)
    test.assertIn(b"history.replaceState", script.data)
    script.close()
    test.assertEqual(browser.post("/staff/enroll", base_url=origin, json={"token":token}).status_code, 403)
    response = browser.post("/staff/enroll", base_url=origin, headers={"Origin":origin}, json={"token":token})
    test.assertEqual(response.status_code, 200)
    cookie = browser.get_cookie(COOKIE, domain="cv.example.test")
    test.assertTrue(cookie.secure and cookie.http_only)
    test.assertEqual((cookie.same_site, cookie.max_age), ("Strict", 90*24*3600))
    raw = cookie.value
    test.assertEqual(browser.get("/api/auth/me", base_url=origin).json["role"], "recruiter")
    replay = app.test_client().post("/staff/enroll", base_url=origin, headers={"Origin":origin}, json={"token":token})
    test.assertEqual(replay.status_code, 401)
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
