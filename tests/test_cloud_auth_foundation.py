"""In-memory auth contract tests. PostgreSQL and real HTTPS integration remain separate."""
import unittest
from datetime import datetime, timedelta, timezone
from cloud.app import create_app, COOKIE
from cloud.auth import Account, Auth, Principal, digest, password_hash

ORIGIN = "https://cv.example.test"
PASSWORD = "synthetic-password-123"

class Store:
    def __init__(self):
        self.accounts = {("a","user@example.test"): Account("a","user-a","recruiter",password_hash(PASSWORD))}
        self.sessions = {}
        self.attempts = {}
    def consume_attempt(self,key,now):
        self.attempts[key] = self.attempts.get(key,0)+1
        return self.attempts[key] <= 10
    def find_account(self,tenant,email):
        return self.accounts.get((tenant,email))
    def create_session(self,d,csrf,a,expires):
        if not any(x == a for x in self.accounts.values()):
            return False
        self.sessions[d] = (csrf,a,expires)
        return True
    def get_session(self,d,now):
        row = self.sessions.get(d)
        if not row:
            return None
        csrf,a,expires = row
        current = next((x for x in self.accounts.values() if (x.tenant_id,x.user_id)==(a.tenant_id,a.user_id)),None)
        if expires <= now or not current or not current.active or current.password_hash != a.password_hash:
            return None
        return Principal(current.tenant_id,current.user_id,current.role,csrf)
    def delete_session(self,d):
        self.sessions.pop(d,None)

class TestAuth(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.client = create_app(auth_store=self.store,public_origin=ORIGIN).test_client()
    def login(self,tenant="a",origin=ORIGIN,password=PASSWORD):
        return self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":origin},json={"tenant":tenant,"email":"user@example.test","password":password})
    def test_cookie_and_revocation(self):
        self.assertEqual(self.client.get("/api/auth/me",base_url=ORIGIN).status_code,401)
        result = self.login()
        self.assertEqual(result.status_code,200)
        cookie=result.headers["Set-Cookie"]
        for part in ("__Host-cvcloud=", "Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(part,cookie)
        raw=self.client.get_cookie(COOKIE,domain="cv.example.test").value
        self.assertIn(digest(raw),self.store.sessions)
        self.assertNotIn(raw,self.store.sessions)
        me=self.client.get("/api/auth/me",base_url=ORIGIN).json
        self.assertEqual(me["tenant_id"],"a")
        self.assertEqual(self.client.post("/api/auth/logout",base_url=ORIGIN,headers={"Origin":ORIGIN}).status_code,403)
        self.assertEqual(self.client.post("/api/auth/logout",base_url=ORIGIN,headers={"Origin":ORIGIN,"X-CSRF-Token":me["csrf"]}).status_code,200)
        self.assertFalse(self.store.sessions)
    def test_origin_tenant_and_host(self):
        self.assertEqual(self.login(origin="https://evil.example").status_code,403)
        self.assertEqual(self.login(tenant="b").status_code,401)
        self.assertEqual(self.login(password="wrong").status_code,401)
        self.assertEqual(self.client.get("/healthz",base_url="https://evil.example").status_code,400)
        self.assertFalse(self.store.sessions)
    def test_expiry_and_disabled_user(self):
        now=datetime.now(timezone.utc)
        clock=[now]
        auth=Auth(self.store,clock=lambda:clock[0])
        raw=auth.login("a","user@example.test",PASSWORD,"test")
        self.assertIsNotNone(auth.principal(raw))
        clock[0]+=timedelta(hours=9)
        self.assertIsNone(auth.principal(raw))
        clock[0]=now
        self.store.accounts[("a","user@example.test")]=Account("a","user-a","recruiter","unused",False)
        self.assertIsNone(auth.principal(raw))
    def test_attempt_limit(self):
        auth=Auth(self.store)
        for _ in range(10):
            self.assertIsNone(auth.login("a","user@example.test","wrong","source"))
        self.assertIsNone(auth.login("a","user@example.test",PASSWORD,"source"))
    def test_password_change_revokes_session(self):
        auth=Auth(self.store)
        raw=auth.login("a","user@example.test",PASSWORD,"test")
        self.assertIsNotNone(auth.principal(raw))
        self.store.accounts[("a","user@example.test")]=Account("a","user-a","recruiter",password_hash("another-synthetic-password"))
        self.assertIsNone(auth.principal(raw))
    def test_source_limit_stops_new_account_buckets(self):
        auth=Auth(self.store)
        for _ in range(10):
            auth.login("a","user@example.test","wrong","source")
        count=len(self.store.attempts)
        auth.login("a","other@example.test","wrong","source")
        self.assertEqual(len(self.store.attempts),count)
    def test_large_login_body_rejected(self):
        response=self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":ORIGIN},json={"tenant":"a","email":"user@example.test","password":"x"*5000})
        self.assertEqual(response.status_code,413)
    def test_invalid_unicode_login_rejected(self):
        auth=Auth(self.store)
        for invalid in ("bad\\ud800@example.test","bad email@example.test","bad\\x00@example.test"):
            self.assertIsNone(auth.login("a",invalid,PASSWORD,"source"))
    def test_default_has_no_auth_routes(self):
        client=create_app().test_client()
        self.assertEqual(client.post("/api/auth/login").status_code,404)
        self.assertEqual(client.get("/readyz").status_code,503)

if __name__=="__main__":
    unittest.main()
