"""Reusable acceptance assertions for the disposable workspace PostgreSQL test.

Call only after fresh workspace initialization with synthetic owners. The
caller owns the disposable DB lifecycle and creates the admin role password.
"""
from uuid import uuid4

def verify_admin_acceptance(test, *, boot_connect, owner_connect, admin_connect, auth_connect, password, owner_a, owner_b):
    import psycopg
    from cloud.auth import Principal,password_hash,Auth,digest,TTL
    from cloud.deploy.online_auth import DedicatedAuthStore
    from datetime import datetime,timezone
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import secrets
    from cloud.account_admin import AccountAdminError
    from cloud.documents_jobs import DocumentJobs,ScopeError
    from cloud.deploy.workspace_admin_install import install
    from cloud.deploy.online_admin_services import OnlineAccountAdmin,OnlineAIUsage
    for _ in range(2):
        install(boot_connect=boot_connect,password=password,admin_connect=admin_connect)

    # Synthetic identities only, on the disposable database.
    recruiter_id=str(uuid4())
    admin_id=str(uuid4())
    foreign_id=str(uuid4())
    with owner_connect() as conn:
        for tenant,user,role,email in (
            (owner_a.tenant_id,recruiter_id,"recruiter","recruiter@example.test"),
            (owner_a.tenant_id,admin_id,"admin","admin@example.test"),
            (owner_b.tenant_id,foreign_id,"recruiter","foreign@example.test"),
        ):
            conn.execute("""INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role)
                VALUES (%s,%s,%s,%s,%s)""",(tenant,user,email,password_hash("fictional-account-acceptance-123"),role))
    recruiter=Principal(owner_a.tenant_id,recruiter_id,"recruiter","")
    manager=Principal(owner_a.tenant_id,admin_id,"admin","")
    service=OnlineAccountAdmin(DocumentJobs(admin_connect))
    usage=OnlineAIUsage(DocumentJobs(admin_connect))
    test.assertEqual({x.user_id for x in service.list_accounts(owner_a)},{owner_a.user_id,recruiter_id,admin_id})
    test.assertEqual({x.user_id for x in service.list_accounts(manager)},{recruiter_id,admin_id})
    test.assertEqual({x.user_id for x in service.list_accounts(owner_b)},{owner_b.user_id,foreign_id})
    with test.assertRaises(AccountAdminError):
        service.list_accounts(recruiter)
    with test.assertRaises(ScopeError):
        usage.snapshot(recruiter)
    # Raw admin SQL cannot directly access sensitive data or mutate accounts.
    for statement in ("SELECT password_hash FROM cvcloud.users","SELECT * FROM cvcloud.sessions",
        "UPDATE cvcloud.users SET role='owner'","DELETE FROM cvcloud.account_audit",
        "SELECT * FROM cvcloud.provider_config","SELECT * FROM cvcloud.documents",
        "SELECT cvcloud.admin_actor_lock()","UPDATE cvcloud.ai_budgets SET limit_microusd=1"):
        with test.assertRaises(psycopg.errors.InsufficientPrivilege):
            with admin_connect() as conn:
                conn.execute(statement)
    for actor,target in ((owner_a,foreign_id),(owner_a,owner_a.user_id),(manager,owner_a.user_id),(recruiter,admin_id)):
        with test.assertRaisesRegex(AccountAdminError,"^account_admin_denied$"):
            service.change(actor,user_id=target,expected_revision=1,action="suspend")
    with test.assertRaises(AccountAdminError):
        service.change(manager,user_id=recruiter_id,expected_revision=1,action="role_change",value="admin")
    auth=Auth(DedicatedAuthStore(auth_connect))
    token=auth.login("one","recruiter@example.test","fictional-account-acceptance-123","192.0.2.3")
    test.assertIsNotNone(auth.principal(token))
    suspended=service.change(manager,user_id=recruiter_id,expected_revision=1,action="suspend")
    test.assertIsNone(auth.principal(token))
    test.assertFalse(suspended.active)
    test.assertEqual(suspended.revision,2)
    with test.assertRaisesRegex(AccountAdminError,"^account_conflict$"):
        service.change(manager,user_id=recruiter_id,expected_revision=1,action="reactivate")
    test.assertTrue(service.change(manager,user_id=recruiter_id,expected_revision=2,action="reactivate").active)
    promoted=service.change(owner_a,user_id=recruiter_id,expected_revision=3,action="role_change",value="admin")
    test.assertEqual((promoted.role,promoted.revision),("admin",4))
    # Race a previously checked login against explicit session revocation.
    # Whichever transaction wins, the old credential revision must not
    # leave an authenticated session after revocation completes.
    store=DedicatedAuthStore(auth_connect)
    checked=store.find_account("one","recruiter@example.test")
    test.assertEqual(checked.credential_version,4)
    raw=secrets.token_urlsafe(32)
    gate=Barrier(2,timeout=10)
    def login_race():
        gate.wait()
        return store.create_session(digest(raw),secrets.token_urlsafe(32),checked,datetime.now(timezone.utc)+TTL)
    def revoke_race():
        gate.wait()
        return service.change(owner_a,user_id=recruiter_id,expected_revision=4,action="revoke_sessions")
    with ThreadPoolExecutor(max_workers=2) as pool:
        login=pool.submit(login_race)
        revoke=pool.submit(revoke_race)
        test.assertEqual(revoke.result(timeout=20).revision,5)
        test.assertIn(login.result(timeout=20),(True,False))
    test.assertIsNone(auth.principal(raw))
    with owner_connect() as conn:
        conn.execute("SELECT set_config('cvcloud.tenant_id',%s,true),set_config('cvcloud.user_id',%s,true)",
            (owner_a.tenant_id,owner_a.user_id))
        events=conn.execute("SELECT action FROM cvcloud.account_audit WHERE tenant_id=%s AND target_id=%s",
            (owner_a.tenant_id,recruiter_id)).fetchall()
        test.assertCountEqual([row[0] for row in events],["suspend","reactivate","role_change","revoke_sessions"])
