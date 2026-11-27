import unittest
from unittest.mock import Mock
from dataclasses import replace
from uuid import uuid4
from cloud.app import create_app
from cloud.account_admin import AccountStatus,AccountAdminError
from tests.test_cloud_auth_foundation import Store,ORIGIN,PASSWORD

URL="/api/admin/accounts"
class TestAccountAdminAPI(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.service=Mock()
        self.target=str(uuid4())
        self.service.list_accounts.return_value=(AccountStatus(self.target,"fictional@example.test","recruiter",True,1),)
        self.service.change.return_value=AccountStatus(self.target,"fictional@example.test","recruiter",False,2)
        self.client=create_app(auth_store=self.store,public_origin=ORIGIN,account_admin=self.service).test_client()
        self.action=URL+"/"+self.target+"/actions"
    def login(self,role="owner"):
        key=("a","user@example.test")
        self.store.accounts[key]=replace(self.store.accounts[key],role=role)
        self.assertEqual(self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":ORIGIN},json={"tenant":"a","email":"user@example.test","password":PASSWORD}).status_code,200)
        self.headers={"Origin":ORIGIN,"X-CSRF-Token":self.client.get("/api/auth/me",base_url=ORIGIN).json["csrf"]}
    def post(self,payload,headers=None):
        return self.client.post(self.action,base_url=ORIGIN,headers=self.headers if headers is None else headers,json=payload)
    def test_opt_in_and_permissions(self):
        self.assertEqual(create_app().test_client().get(URL).status_code,404)
        with self.assertRaises(ValueError):
            create_app(account_admin=self.service)
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,401)
        self.login("recruiter")
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,403)
        self.assertEqual(self.post({"action":"suspend","expected_revision":"1"}).status_code,403)
        self.service.change.assert_not_called()
    def test_list_and_action(self):
        self.login()
        result=self.client.get(URL,base_url=ORIGIN)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        self.assertEqual(set(result.json["items"][0]),{"user_id","email","role","active","revision"})
        self.assertEqual(result.json["items"][0]["revision"],"1")
        body={"action":"suspend","expected_revision":"1"}
        self.assertEqual(self.post(body,{}).status_code,403)
        self.assertEqual(self.post(body,dict(self.headers,Origin="https://evil.example")).status_code,403)
        result=self.post(body)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json["account"]["revision"],"2")
        self.assertEqual(self.service.change.call_args.kwargs,{"user_id":self.target,"expected_revision":1,"action":"suspend","value":None})
        self.assertEqual(self.service.change.call_args.args[0].tenant_id,"a")
    def test_bad_payload_and_conflicts(self):
        self.login()
        for body in ({"action":"password_reset","expected_revision":"1","value":"fictional"},
            {"action":"role_change","expected_revision":"1","value":"owner"},
            {"action":"suspend","expected_revision":1},{"action":"suspend","expected_revision":"01"},
            {"action":"suspend","expected_revision":"0"},{"action":"suspend","expected_revision":"1","tenant_id":"other"}):
            self.assertEqual(self.post(body).status_code,400)
        self.service.change.assert_not_called()
        self.service.change.side_effect=AccountAdminError("account_conflict")
        self.assertEqual(self.post({"action":"suspend","expected_revision":"1"}).status_code,409)
        self.service.change.side_effect=AccountAdminError("account_admin_denied")
        self.assertEqual(self.post({"action":"suspend","expected_revision":"1"}).status_code,403)
        self.assertEqual(self.client.get(URL+"?tenant_id=other",base_url=ORIGIN).status_code,400)
