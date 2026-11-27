import unittest
from flask import Flask
from lxml import html
from cloud.frontend.shell import render_shell,register_existing_ui,ASSETS

class TestExistingShell(unittest.TestCase):
    def test_original_markup_and_no_desktop_handlers(self):
        root=html.fromstring(render_shell())
        for key in ("btnFormat","btnBlind","btnDocx","cvInput","fileInput","outputBox","cloudClearInput","cloudLogin"):
            self.assertEqual(len(root.xpath(".//*[@id=$key]",key=key)),1,key)
        self.assertEqual([n.get("id") for n in root.xpath(".//*[@id='pageTabs']/button")],["tabFormat","tabBatch","tabJDAnon","tabCompany","tabAppraiser"])
        self.assertFalse(root.xpath(".//*[@id='tabJobLeads' or @id='jaBar' or @id='settingsPanel']"))
        self.assertFalse(root.xpath(".//iframe | .//object | .//embed"))
        for node in root.iter():
            self.assertFalse(any(k.lower().startswith("on") for k in node.attrib))
        self.assertEqual({n.get("src") for n in root.xpath(".//script")},{"/cloud-ui/assets/cv_client.js","/cloud-ui/assets/existing_cv_controls.js","/cloud-ui/assets/bootstrap.js"})
        self.assertEqual(root.xpath(".//form")[0].get("method"),"post")
        self.assertEqual(root.xpath(".//*[@id='btnFormat']")[0].get("disabled"),"disabled")
    def test_fail_closed_and_fixed_assets(self):
        app=Flask(__name__,static_folder=None)
        with self.assertRaises(ValueError):
            register_existing_ui(app)
        self.assertEqual(app.test_client().get("/cloud-ui").status_code,404)
        # Use a fresh app: Flask freezes route setup after the first request.
        app=Flask(__name__,static_folder=None)
        # Only synthetic route contracts; real authenticated staging is separate.
        app.extensions["cvcloud_auth"]=object()
        for i,(path,method) in enumerate([("/api/auth/login","POST"),("/api/auth/me","GET"),("/api/auth/logout","POST"),("/api/documents","POST"),("/api/jobs","POST"),("/api/jobs/<uuid:job_id>","GET"),("/api/jobs/<uuid:job_id>/download","GET")]):
            app.add_url_rule(path,str(i),lambda **kw:("fixture",200),methods=[method])
        register_existing_ui(app)
        client=app.test_client()
        response=client.get("/cloud-ui")
        self.assertEqual(response.status_code,200)
        self.assertIn("script-src 'self'",response.headers["Content-Security-Policy"])
        self.assertEqual(response.headers["Cache-Control"],"no-store")
        response.close()
        for name in ASSETS:
            response=client.get("/cloud-ui/assets/"+name)
            self.assertEqual(response.status_code,200)
            response.close()
        self.assertEqual(client.get("/cloud-ui/assets/index.html").status_code,404)
        self.assertEqual(client.get("/vendor/cvstudio/ai-keys.js").status_code,404)

    def test_optional_batch_original_controls(self):
        root=html.fromstring(render_shell(enable_batch=True))
        for key in ("viewBatch","batchFileInput","batchTabFormat","batchTabBlind","btnBatchRun","cloudBatchClear","batchFileList"):
            self.assertEqual(len(root.xpath(".//*[@id=$key]",key=key)),1,key)
        self.assertIsNone(root.xpath(".//*[@id='tabBatch']")[0].get("disabled"))
        self.assertIsNotNone(root.xpath(".//*[@id='batchFileInput']")[0].get("multiple"))
        self.assertFalse(root.xpath(".//*[@id='batchAiQuickPanel' or @id='batchJAStatus' or @id='btnBatchDownload']"))
        self.assertTrue(root.xpath(".//script[@src='/cloud-ui/assets/batch_cloud.js']"))
        for node in root.iter():
            self.assertFalse(any(k.lower().startswith("on") for k in node.attrib))

    def test_optional_history_panel(self):
        root=html.fromstring(render_shell(enable_batch=True,enable_history=True))
        for key in ("cloudHistoryToggle","cloudHistoryPanel","cloudHistoryJobs","cloudHistoryDocuments","cloudHistoryRefresh","cloudHistoryNext","cloudHistoryList","batchFileInput"):
            self.assertEqual(len(root.xpath(".//*[@id=$key]",key=key)),1,key)
        self.assertTrue(root.xpath(".//script[@src='/cloud-ui/assets/history_cloud.js']"))
        self.assertFalse(html.fromstring(render_shell()).xpath(".//*[@id='cloudHistoryPanel']"))
        for node in root.iter():
            self.assertFalse(any(k.lower().startswith("on") for k in node.attrib))
