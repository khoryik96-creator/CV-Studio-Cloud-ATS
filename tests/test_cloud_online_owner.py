import unittest
from cloud.deploy.online_owner import normalize_owner, provision_owner
from cloud.deploy.online_serve import server_options

class OwnerInputsTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_owner("hyppies"," Owner@Example.test ","a-long-owner-password"),("hyppies","owner@example.test"))
        for tenant,email,pw in (("Bad","x@y.test","a-long-owner-password"),("a","@test","a-long-owner-password"),("a","x@y.test","short"),("a","x@y.test","long-password\x00here")):
            with self.subTest(tenant=tenant,email=email),self.assertRaises(ValueError):
                normalize_owner(tenant,email,pw)

    def test_server_options_preserve_raw_proxy_headers(self):
        options=server_options()
        self.assertFalse(options["clear_untrusted_proxy_headers"])
        self.assertNotIn("trusted_proxy",options)
        self.assertFalse(options["expose_tracebacks"])
        self.assertEqual(options["max_request_body_size"],4096)

    def test_wrong_database_refused(self):
        class Result:
            def fetchone(self):
                return ("hiringplug","cvcloud_schema_owner","cvcloud_schema_owner",True,True,True)
        class Connection:
            def __enter__(self):
                return self
            def __exit__(self,*args):
                pass
            def execute(self,sql,*args):
                if not sql.startswith("SELECT current_database()"):
                    raise AssertionError("unexpected database mutation")
                return Result()
        with self.assertRaises(RuntimeError):
            provision_owner(Connection,tenant="test",email="owner@example.test",password="a-long-owner-password")

    def test_actual_waitress_forwarding(self):
        import http.client
        import json
        from threading import Thread
        from waitress import create_server
        from cloud.app import create_app
        from cloud.deploy.online_auth import TrustedProxyOnly
        from tests.test_cloud_auth_foundation import Store,PASSWORD
        origin="https://cvstudio.hyplug.co"
        app=TrustedProxyOnly(create_app(auth_store=Store(),public_origin=origin),"127.0.0.1")
        server=create_server(app,host="127.0.0.1",port=0,**server_options())
        thread=Thread(target=server.run,daemon=True)
        thread.start()
        def request(headers,body=None):
            conn=http.client.HTTPConnection("127.0.0.1",int(server.effective_port),timeout=5)
            try:
                conn.request("GET" if body is None else "POST",
                    "/readyz" if body is None else "/api/auth/login",body=body,headers=headers)
                response=conn.getresponse()
                response.read()
                return response.status,response.getheader("Set-Cookie")
            finally:
                conn.close()
        try:
            headers={"Host":"cvstudio.hyplug.co","Origin":origin,"Content-Type":"application/json"}
            payload=json.dumps({"tenant":"a","email":"user@example.test","password":PASSWORD})
            self.assertEqual(request(headers)[0],403)
            forwarded=dict(headers,**{"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https"})
            self.assertEqual(request(forwarded)[0],503)
            self.assertEqual(request(dict(forwarded,**{"X-Forwarded-For":"192.0.2.1, 192.0.2.2"}),payload)[0],403)
            status,cookie=request(forwarded,payload)
            self.assertEqual(status,200)
            self.assertIn("Secure",cookie)
        finally:
            server.task_dispatcher.shutdown()
            server.close()
            thread.join(timeout=2)
