import tempfile
import unittest
from pathlib import Path
from werkzeug.test import Client
from werkzeug.wrappers import Response
from cloud.app import create_app
from cloud.deploy.online_auth import read_config, TrustedProxyOnly
from tests.test_cloud_auth_foundation import Store, PASSWORD

ORIGIN="https://cvstudio.hyplug.co"
PROXY="172.29.0.2"

class OnlineAuthTest(unittest.TestCase):
    def test_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            secret=Path(tmp)/"secret"
            secret.write_text("x"*32,encoding="utf-8")
            env={"CVCLOUD_PUBLIC_ORIGIN":ORIGIN,"CVCLOUD_TRUSTED_PROXY_IP":PROXY,
                 "CVCLOUD_AUTH_PASSWORD_FILE":str(secret)}
            cfg=read_config(env)
            self.assertEqual(cfg.origin,ORIGIN)
            self.assertNotIn("x"*32,repr(cfg))
            for invalid in ("http://cvstudio.hyplug.co","https://cv.example.test","https://cvstudio.hyplug.co:443","https://cvstudio.hyplug.co/","https://user@cvstudio.hyplug.co"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    read_config(dict(env,CVCLOUD_PUBLIC_ORIGIN=invalid))
            for invalid in ("","172.29.0.2,172.29.0.3","0.0.0.0"):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    read_config(dict(env,CVCLOUD_TRUSTED_PROXY_IP=invalid))
            secret.write_text("short",encoding="utf-8")
            with self.assertRaises(ValueError):
                read_config(env)

    def test_proxy_and_auth(self):
        store=Store()
        app=create_app(auth_store=store,public_origin=ORIGIN)
        client=Client(TrustedProxyOnly(app,PROXY),Response)
        headers={"Origin":ORIGIN,"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https"}
        body={"tenant":"a","email":"user@example.test","password":PASSWORD}
        def login(peer=PROXY, **changes):
            return client.post("/api/auth/login",base_url=ORIGIN,json=body,
                headers=dict(headers,**changes),environ_overrides={"REMOTE_ADDR":peer})
        self.assertEqual(login(peer="172.29.0.3").status_code,403)
        self.assertEqual(login(**{"X-Forwarded-For":"192.0.2.1, 192.0.2.2"}).status_code,403)
        self.assertEqual(login(**{"X-Forwarded-Proto":"http"}).status_code,403)
        self.assertEqual(login(Origin="https://hyplug.co").status_code,403)
        response=login()
        self.assertEqual(response.status_code,200)
        self.assertIn("Secure",response.headers["Set-Cookie"])
        self.assertEqual(client.get("/readyz",base_url=ORIGIN,headers=headers,
            environ_overrides={"REMOTE_ADDR":PROXY}).status_code,503)
        self.assertEqual(client.post("/parse",base_url=ORIGIN,headers=headers,
            environ_overrides={"REMOTE_ADDR":PROXY}).status_code,404)


class OnlineAuthPostgresTest(unittest.TestCase):
    def test_dedicated_role_and_session(self):
        import os
        if os.environ.get("CVCLOUD_REQUIRE_ONLINE_AUTH_DB") != "1":
            self.skipTest("Explicit disposable PostgreSQL test required")
        import secrets
        import psycopg
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        from cloud.auth import password_hash
        from cloud.deploy.online_auth import OnlineAuthConfig, build_online_auth
        admin_dsn=os.environ["CVCLOUD_TEST_DSN"]
        parsed=conninfo_to_dict(admin_dsn)
        if parsed.get("dbname")!="cvcloud_test" or parsed.get("host")!="127.0.0.1":
            self.fail("Refusing non-disposable CI database")
        root=Path(__file__).resolve().parents[1]
        pw=secrets.token_hex(24)
        created_role=created_db=False
        admin=psycopg.connect(admin_dsn,autocommit=True)
        try:
            from psycopg import sql
            admin.execute(sql.SQL("CREATE ROLE cvcloud_auth LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB NOREPLICATION PASSWORD {}").format(sql.Literal(pw)))
            created_role=True
            admin.execute("CREATE DATABASE cvcloud_online")
            created_db=True
            online_admin=make_conninfo(admin_dsn,dbname="cvcloud_online")
            with psycopg.connect(online_admin,autocommit=True) as db:
                for path in ("cloud/migrations/001_auth.sql","cloud/migrations/004_auth_epoch.sql","cloud/deploy/online_auth_grants.sql"):
                    db.execute((root/path).read_text(encoding="utf-8"),prepare=False)
                tenant="10000000-0000-4000-8000-000000000001"
                user="20000000-0000-4000-8000-000000000001"
                db.execute("INSERT INTO cvcloud.tenants (id,slug) VALUES (%s,'a')",(tenant,))
                db.execute("INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role) VALUES (%s,%s,'user@example.test',%s,'owner')",(tenant,user,password_hash(PASSWORD)))
            runtime=make_conninfo(admin_dsn,dbname="cvcloud_online",user="cvcloud_auth",password=pw)
            def connect():
                return psycopg.connect(runtime)
            app=build_online_auth(config=OnlineAuthConfig(ORIGIN,PROXY,pw),connect=connect)
            client=Client(app,Response)
            headers={"Origin":ORIGIN,"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https"}
            peer={"REMOTE_ADDR":PROXY}
            self.assertEqual(client.post("/api/auth/login",base_url=ORIGIN,headers=headers,environ_overrides=peer,
                json={"tenant":"a","email":"user@example.test","password":PASSWORD}).status_code,200)
            self.assertEqual(client.get("/api/auth/me",base_url=ORIGIN,headers=headers,environ_overrides=peer).json["role"],"owner")
            for statement in ("UPDATE cvcloud.users SET role='recruiter'","UPDATE cvcloud.tenants SET active=false"):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with connect() as db:
                        db.execute(statement)
            with psycopg.connect(online_admin) as db:
                db.execute("UPDATE cvcloud.users SET active=false")
            self.assertEqual(client.get("/api/auth/me",base_url=ORIGIN,headers=headers,environ_overrides=peer).status_code,401)
        finally:
            try:
                if created_db:
                    admin.execute("DROP DATABASE cvcloud_online WITH (FORCE)")
                if created_role:
                    admin.execute("DROP ROLE cvcloud_auth")
            finally:
                admin.close()
