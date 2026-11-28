import unittest
from unittest.mock import Mock
from dataclasses import replace
from cloud.app import create_app
from cloud.provider_config import ProviderStatus,ProviderConfigError
from tests.test_cloud_auth_foundation import Store,ORIGIN,PASSWORD

URL="/api/admin/ai-provider"

class TestProviderAdminAPI(unittest.TestCase):
    def setUp(self):
        self.store=Store()
        self.service=Mock()
        self.service.status.return_value=None
        self.service.choices.return_value=(("deepseek","fictional-model"),)
        self.service.configure.return_value=ProviderStatus(1,"deepseek","fictional-model",True)
        self.service.disable.return_value=ProviderStatus(2,"deepseek","fictional-model",False)
        self.client=create_app(auth_store=self.store,public_origin=ORIGIN,provider_admin=self.service).test_client()
    def login(self,role="admin"):
        key=("a","user@example.test")
        self.store.accounts[key]=replace(self.store.accounts[key],role=role)
        self.assertEqual(self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":ORIGIN},
            json={"tenant":"a","email":"user@example.test","password":PASSWORD}).status_code,200)
        self.headers={"Origin":ORIGIN,"X-CSRF-Token":self.client.get("/api/auth/me",base_url=ORIGIN).json["csrf"]}
    def payload(self):
        return {"provider":"deepseek","model":"fictional-model","secret":"fictional-test-key","expected_revision":"0"}
    def test_opt_in_and_role(self):
        self.assertEqual(create_app().test_client().get(URL).status_code,404)
        with self.assertRaises(ValueError):
            create_app(provider_admin=self.service)
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,401)
        self.login("recruiter")
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,403)
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=self.payload()).status_code,403)
        self.service.configure.assert_not_called()
    def test_redacted_status_and_write(self):
        self.login()
        result=self.client.get(URL,base_url=ORIGIN)
        self.assertEqual(result.json["configuration"]["revision"],"0")
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        self.assertEqual(result.json["choices"],[{"provider":"deepseek","model":"fictional-model"}])
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,json=self.payload()).status_code,403)
        result=self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=self.payload())
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json["configuration"]["revision"],"1")
        self.assertNotIn("fictional-test-key",result.get_data(as_text=True))
        self.assertEqual(self.service.configure.call_args.kwargs["expected_revision"],0)
        self.assertEqual(self.service.configure.call_args.args[0].tenant_id,"a")
        result=self.client.post(URL+"/disable",base_url=ORIGIN,headers=self.headers,json={"expected_revision":"1"})
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json["configuration"]["enabled"])
    def test_bad_origin_revision_extra_fields_and_conflict(self):
        self.login()
        payload=self.payload()
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,headers=dict(self.headers,Origin="https://evil.example"),json=payload).status_code,403)
        for value in (0,True,"01","-1","9223372036854775807","9"*30):
            self.assertEqual(self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=dict(payload,expected_revision=value)).status_code,400)
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=dict(payload,tenant_id="other")).status_code,400)
        self.service.configure.assert_not_called()
        self.service.configure.side_effect=ProviderConfigError("configuration_conflict")
        self.assertEqual(self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=payload).status_code,409)
        self.service.configure.side_effect=ProviderConfigError("fictional-test-key")
        result=self.client.post(URL,base_url=ORIGIN,headers=self.headers,json=payload)
        self.assertEqual(result.status_code,400)
        self.assertNotIn("fictional-test-key",result.get_data(as_text=True))
    def test_role_revocation_at_service_boundary(self):
        self.login("owner")
        self.service.status.side_effect=ProviderConfigError("provider_access_denied")
        self.assertEqual(self.client.get(URL,base_url=ORIGIN).status_code,403)

    def test_composition_with_document_scoring_and_account_services(self):
        app=create_app(auth_store=self.store,public_origin=ORIGIN,
            cv_services=(Mock(),Mock(),Mock()),enable_scoring=True,
            provider_admin=self.service,account_admin=Mock(),ai_usage=Mock())
        rules={(r.rule,m):r.endpoint for r in app.url_map.iter_rules() for m in r.methods}
        self.assertNotEqual(rules[("/api/jobs/<uuid:job_id>","GET")],
            rules[("/api/admin/ai-provider","GET")])
        client=app.test_client()
        for path in (URL,"/api/admin/accounts","/api/admin/ai-usage","/api/scoring/jobs"):
            self.assertEqual(client.get(path,base_url=ORIGIN).status_code,401)
