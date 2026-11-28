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
