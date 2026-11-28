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


    def test_browser_activation(self):
        # Required in Linux cloud CI; legacy desktop runners need not install Chromium.
        import os
        if os.environ.get("CVCLOUD_REQUIRE_BROWSER") != "1":
            self.skipTest("Cloud browser gate not enabled")
        from playwright.sync_api import sync_playwright, expect
        # Serve real Flask responses to Chromium at the synthetic HTTPS origin.
        # No external network, real credentials, TLS listener or provider is used.
        posts=[]
        unexpected=[]
        def dispatch(route):
            req=route.request
            if not req.url.startswith(ORIGIN+"/"):
                unexpected.append(req.url)
                route.abort()
                return
            path=req.url[len(ORIGIN):]
            if req.method=="POST":
                posts.append((path,req.post_data_json))
            response=self.client.open(path,method=req.method,base_url=ORIGIN,
                                      headers=req.all_headers(),data=req.post_data)
            try:
                route.fulfill(status=response.status_code,
                              headers=dict(response.headers),
                              body=response.get_data())
            finally:
                response.close()

        with sync_playwright() as pw:
            browser=pw.chromium.launch()
            try:
                context=browser.new_context(service_workers="block")
                context.route("**/*",dispatch)
                page=context.new_page()
                page.goto(ORIGIN+"/activate")
                status=page.locator("#activationStatus")
                expect(status).to_have_text("Ready.")
                code=page.locator("#activationCode")
                password=page.locator("#activationPassword")
                confirm=page.locator("#activationConfirm")
                submit=page.locator("#activationSubmit")
                def enter(confirmation=PASSWORD):
                    code.fill(TOKEN)
                    password.fill(PASSWORD)
                    confirm.fill(confirmation)
                    submit.click()
                enter("mismatching-password")
                expect(status).to_contain_text("matching passwords")
                self.assertEqual(posts,[])
                for field in (code,password,confirm):
                    expect(field).to_have_value("")
                self.service.redeem.return_value=False
                enter()
                expect(status).to_contain_text("Code invalid")
                expect(submit).to_be_enabled()
                self.service.redeem.return_value=True
                enter()
                expect(status).to_have_text("Password set. Return to sign in.")
                expect(submit).to_be_disabled()
                for field in (code,password,confirm):
                    expect(field).to_have_value("")
                self.assertEqual(posts,[(URL,{"token":TOKEN,"password":PASSWORD})]*2)
                self.assertEqual(self.service.redeem.call_count,2)
                self.assertEqual(page.url,ORIGIN+"/activate")
                self.assertEqual(context.cookies(),[])
                self.assertEqual(page.evaluate("() => [localStorage.length, sessionStorage.length]"),[0,0])
                self.assertEqual(unexpected,[])
            finally:
                browser.close()
