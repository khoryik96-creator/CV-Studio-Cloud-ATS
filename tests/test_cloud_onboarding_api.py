import unittest
from unittest.mock import Mock
from cloud.app import create_app
from cloud.auth import digest
from tests.test_cloud_auth_foundation import Store,ORIGIN

URL="/api/auth/redeem"
TOKEN="A"*43
PASSWORD="fictional-password-123"

class TestOnboardingAPI(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.service=Mock()
        self.service.redeem.return_value=True
        self.client=create_app(auth_store=self.store,public_origin=ORIGIN,onboarding=self.service).test_client()
    def post(self,body,origin=ORIGIN,source="127.0.0.1"):
        return self.client.post(URL,base_url=ORIGIN,headers={"Origin":origin},json=body,environ_overrides={"REMOTE_ADDR":source})
    def test_opt_in_and_success(self):
        self.assertEqual(create_app().test_client().post(URL).status_code,404)
        with self.assertRaises(ValueError):
            create_app(onboarding=self.service)
        result=self.post({"token":TOKEN,"password":PASSWORD})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json,{"ok":True})
        self.assertNotIn("Set-Cookie",result.headers)
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        self.service.redeem.assert_called_once_with(TOKEN,PASSWORD)
    def test_invalid_and_origin(self):
        self.assertEqual(self.post({"token":TOKEN,"password":PASSWORD},origin="https://evil.example").status_code,403)
        for body in ({"token":"bad","password":PASSWORD},{"token":TOKEN,"password":"short"},{"token":TOKEN,"password":PASSWORD,"tenant":"other"}):
            self.assertEqual(self.post(body).status_code,400)
        self.service.redeem.assert_not_called()
        self.service.redeem.return_value=False
        response=self.post({"token":TOKEN,"password":PASSWORD})
        self.assertEqual(response.status_code,400)
        self.assertNotIn(TOKEN,response.get_data(as_text=True))
    def test_source_and_token_throttles(self):
        self.service.redeem.return_value=False
        for _ in range(10):
            self.assertEqual(self.post({"token":TOKEN,"password":PASSWORD}).status_code,400)
        count=len(self.store.attempts)
        self.assertEqual(self.post({"token":"B"*43,"password":PASSWORD}).status_code,429)
        self.assertEqual(len(self.store.attempts),count)
        self.assertEqual(self.post({"token":TOKEN,"password":PASSWORD},source="127.0.0.2").status_code,429)
        self.assertEqual(self.service.redeem.call_count,10)
        self.assertIn(digest("redeem:token:"+TOKEN),self.store.attempts)

    def test_activation_page_security(self):
        self.assertEqual(create_app().test_client().get("/activate").status_code,404)
        result=self.client.get("/activate",base_url=ORIGIN)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        self.assertEqual(result.headers["Referrer-Policy"],"no-referrer")
        self.assertIn("form-action 'none'",result.headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'",result.headers["Content-Security-Policy"])
        self.assertNotIn('name="token"',result.get_data(as_text=True))
        self.assertNotIn('name="password"',result.get_data(as_text=True))
        self.assertEqual(self.client.get("/activate?token="+TOKEN,base_url=ORIGIN).status_code,400)
        for path in ("/activate/client.js","/activate/style.css"):
            response=self.client.get(path,base_url=ORIGIN)
            self.assertEqual(response.status_code,200)
            response.close()
