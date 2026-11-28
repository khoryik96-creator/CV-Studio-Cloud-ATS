import unittest
from unittest.mock import Mock
from uuid import uuid4
from cloud.app import create_app
from cloud.job_outputs import Download
from tests.test_cloud_auth_foundation import Store,ORIGIN,PASSWORD

class TestCvApi(unittest.TestCase):
    def setUp(self):
        self.uploads,self.repo,self.outputs=Mock(),Mock(),Mock()
        self.doc,self.job=str(uuid4()),str(uuid4())
        self.uploads.upload.return_value=self.doc
        self.repo.enqueue.return_value=self.job
        self.repo.job.return_value=(self.job,"cv_formatting","queued",self.doc,2300)
        self.client=create_app(auth_store=Store(),public_origin=ORIGIN,cv_services=(self.uploads,self.repo,self.outputs)).test_client()
    def login(self):
        self.assertEqual(self.client.post("/api/auth/login",base_url=ORIGIN,headers={"Origin":ORIGIN},
            json={"tenant":"a","email":"user@example.test","password":PASSWORD}).status_code,200)
        self.headers={"Origin":ORIGIN,"X-CSRF-Token":self.client.get("/api/auth/me",base_url=ORIGIN).json["csrf"]}
    def test_default_route_disabled(self):
        self.assertEqual(create_app().test_client().post("/api/documents").status_code,404)
    def test_auth_and_csrf(self):
        self.assertEqual(self.client.post("/api/documents",base_url=ORIGIN,data=b"cv",content_type="text/plain").status_code,401)
        self.login()
        self.assertEqual(self.client.post("/api/documents",base_url=ORIGIN,data=b"cv",content_type="text/plain").status_code,403)
        self.uploads.upload.assert_not_called()
        res=self.client.post("/api/documents",base_url=ORIGIN,headers=self.headers,data=b"cv",content_type="text/plain")
        self.assertEqual((res.status_code,res.json["document_id"]),(201,self.doc))
        self.assertEqual(self.uploads.upload.call_args.kwargs["byte_size"],2)
    def test_job_scope_and_options(self):
        self.login()
        body={"document_id":self.doc,"module":"cv_formatting","idempotency_key":str(uuid4()),"alignment":"justify"}
        res=self.client.post("/api/jobs",base_url=ORIGIN,headers=self.headers,json=body)
        self.assertEqual((res.status_code,res.json["job_id"]),(202,self.job))
        self.assertEqual(self.repo.enqueue.call_args.kwargs["options"].alignment,"justify")
        for bad in (dict(body,module="jobadder"),dict(body,tenant_id="other"),dict(body,neutral_gender=True)):
            self.assertEqual(self.client.post("/api/jobs",base_url=ORIGIN,headers=self.headers,json=bad).status_code,400)
        status=self.client.get("/api/jobs/"+self.job,base_url=ORIGIN).json
        self.assertEqual((status["state"],status["elapsed_ms"]),("queued",2300))
        self.assertEqual(self.repo.job.call_args.args[1:], (self.job,))
        self.assertEqual(self.repo.job.call_args.kwargs, {"include_elapsed": True})
    def test_review_download(self):
        self.login()
        self.outputs.download.return_value=Download(b"fictional",True)
        url="/api/jobs/"+self.job+"/download"
        self.assertEqual(self.client.get(url,base_url=ORIGIN).status_code,409)
        result=self.client.get(url+"?review=1",base_url=ORIGIN)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers["X-CV-Review-Required"],"1")
        self.assertIn("attachment",result.headers["Content-Disposition"])
        self.assertEqual(result.headers["Cache-Control"],"no-store")

    def test_preview_authorization_and_review(self):
        import io,zipfile
        url="/api/jobs/"+self.job+"/preview"
        self.assertEqual(self.client.get(url,base_url=ORIGIN).status_code,401)
        self.login()
        self.outputs.download.return_value=None
        self.assertEqual(self.client.get(url,base_url=ORIGIN).status_code,404)
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            z.writestr("word/document.xml",'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Fictional &amp; safe</w:t></w:r></w:p></w:body></w:document>')
        self.outputs.download.return_value=Download(buf.getvalue(),True)
        self.assertEqual(self.client.get(url,base_url=ORIGIN).status_code,409)
        result=self.client.get(url+"?review=1",base_url=ORIGIN)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json["paragraphs"],["Fictional & safe"])
        self.assertTrue(result.json["requires_review"])
        self.assertEqual(result.headers["Cache-Control"],"no-store")

    def test_history_read_boundary(self):
        self.assertEqual(self.client.get("/api/jobs",base_url=ORIGIN).status_code,401)
        self.login()
        self.repo.history.return_value={"items":[],"next_cursor":None}
        result=self.client.get("/api/jobs?limit=10",base_url=ORIGIN)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.headers["Cache-Control"],"no-store")
        self.assertEqual(self.repo.history.call_args.kwargs,{"kind":"jobs","limit":10,"before":None})
        self.assertEqual(self.client.get("/api/documents?before="+self.doc,base_url=ORIGIN).status_code,200)
        self.assertEqual(self.repo.history.call_args.kwargs,{"kind":"documents","limit":25,"before":self.doc})
        for query in ("limit=0&limit=2","limit=000","limit=abc","limit=100","before=bad","owner_id=other"):
            self.assertEqual(self.client.get("/api/jobs?"+query,base_url=ORIGIN).status_code,400)
