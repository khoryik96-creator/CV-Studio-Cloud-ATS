import unittest
from unittest.mock import Mock
from dataclasses import replace
from cloud.app import create_app
from tests.test_cloud_auth_foundation import Store,ORIGIN,PASSWORD
from cloud.documents_jobs import ScopeError

URL="/api/admin/ai-usage"
class TestAIUsage(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.service=Mock()
        self.service.snapshot.return_value={"configured":False}
        self.client=create_app(auth_store=self.store,public_origin=ORIGIN,ai_usage=self.service).test_client()
    def login(self,role):
        key=("a","user@example.test")
        self.store.accounts[key]=replace(self.store.accounts[key],role=role)
        self.assertEqual(self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":ORIGIN},json={"tenant":"a","email":"user@example.test","password":PASSWORD}).status_code,200)
    def test_opt_in_and_authorization(self):
        self.assertEqual(create_app().test_client().get(URL).status_code,404)
        with self.assertRaises(ValueError):
            create_app(ai_usage=self.service)
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,401)
        self.login("recruiter")
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,403)
        self.service.snapshot.assert_not_called()
    def test_admin_read_only_and_scope(self):
        self.login("admin")
        response=self.client.get(URL,base_url=ORIGIN)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json,{"configured":False})
        self.assertEqual(response.headers["Cache-Control"],"no-store")
        self.assertEqual(self.service.snapshot.call_args.args[0].tenant_id,"a")
        self.assertEqual(self.client.get(URL+"?tenant_id=b",base_url=ORIGIN).status_code,400)
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,json={}).status_code,405)
        self.service.snapshot.side_effect=ScopeError("denied")
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,403)
