"""Explicit destructive integration fixture: run only against disposable CI database."""
import os
import unittest
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
import psycopg
from cloud.auth import Auth,password_hash
from cloud.auth_postgres import PostgresAuthStore
from cloud.documents_jobs import DocumentJobs,ScopeError,JobConflict

DSN=os.environ.get("CVCLOUD_TEST_DSN")
RUNTIME_DSN=os.environ.get("CVCLOUD_TEST_RUNTIME_DSN")

@unittest.skipUnless(DSN and RUNTIME_DSN,"Disposable PostgreSQL integration DSNs required")
class TestPostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Fresh ephemeral CI DB only. Refuse to overwrite existing schema.
        with psycopg.connect(DSN,autocommit=True) as conn:
            for path in sorted((Path(__file__).resolve().parents[1]/"cloud"/"migrations").glob("*.sql")):
                conn.execute(path.read_text(),prepare=False)
            conn.execute("GRANT USAGE ON SCHEMA cvcloud TO cvcloud_runtime")
            conn.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA cvcloud TO cvcloud_runtime")
        cls.connect=staticmethod(lambda:psycopg.connect(RUNTIME_DSN))
        cls.auth=Auth(PostgresAuthStore(cls.connect))
    def setUp(self):
        self.ids=[(str(uuid4()),str(uuid4()),"t"+uuid4().hex) for _ in range(2)]
        with psycopg.connect(DSN) as conn:
            for tenant,user,slug in self.ids:
                conn.execute("INSERT INTO cvcloud.tenants (id,slug) VALUES (%s,%s)",(tenant,slug))
                conn.execute("INSERT INTO cvcloud.users (tenant_id,id,email_normalized,password_hash,role) VALUES (%s,%s,%s,%s,%s)",(tenant,user,"synthetic@example.test",password_hash("synthetic-password-123"),"recruiter"))
        self.tokens=[self.auth.login(slug,"synthetic@example.test","synthetic-password-123",slug) for _,_,slug in self.ids]
        self.principals=[self.auth.principal(token) for token in self.tokens]
        self.repo=DocumentJobs(self.connect)
    def test_isolation_and_idempotency(self):
        a,b=self.principals
        doc=self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64)
        self.assertIsNotNone(self.repo.document(a,doc))
        self.assertIsNone(self.repo.document(b,doc))
        key=str(uuid4())
        with self.assertRaises(ScopeError):
            self.repo.enqueue(b,document_id=doc,module="cv_blinding",idempotency_key=key)
        job=self.repo.enqueue(a,document_id=doc,module="cv_blinding",idempotency_key=key)
        self.assertEqual(job,self.repo.enqueue(a,document_id=doc,module="cv_blinding",idempotency_key=key))
        with self.assertRaises(JobConflict):
            self.repo.enqueue(a,document_id=doc,module="cv_formatting",idempotency_key=key)
        self.assertIsNone(self.repo.job(b,job))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM cvcloud.documents").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT count(*) FROM cvcloud.jobs").fetchone()[0],0)
    def test_review_only_documents_do_not_block_new_batches(self):
        a = self.principals[0]
        doc = self.repo.register_document(a, media_type="text/plain", byte_size=10, sha256="a"*64)
        jobs = [self.repo.enqueue(a, document_id=doc, module="cv_blinding", idempotency_key=str(uuid4()))
                for _ in range(10)]
        with self.assertRaises(JobConflict):
            self.repo.enqueue(a, document_id=doc, module="cv_blinding", idempotency_key=str(uuid4()))
        with self.repo.scoped(a) as (conn, tenant, owner):
            # A review state alone can represent an uncertain attempt.
            conn.execute("""UPDATE cvcloud.jobs SET state='needs_review'
                WHERE tenant_id=%s AND owner_id=%s AND id=%s""", (tenant, owner, jobs[0]))
        with self.assertRaises(JobConflict):
            self.repo.enqueue(a, document_id=doc, module="cv_blinding", idempotency_key=str(uuid4()))
        with self.repo.scoped(a) as (conn, tenant, owner):
            conn.execute("""INSERT INTO cvcloud.job_outputs
                (tenant_id,owner_id,job_id,object_id,byte_size,sha256,requires_review)
                VALUES (%s,%s,%s,%s,10,%s,true)""", (tenant,owner,jobs[0],str(uuid4()),"b"*64))
        self.assertIsNotNone(self.repo.enqueue(a, document_id=doc, module="cv_blinding", idempotency_key=str(uuid4())))

    def test_cv_job_elapsed_is_owner_scoped_and_stops_at_completion(self):
        principal, other = self.principals
        doc = self.repo.register_document(principal, media_type="text/plain", byte_size=10, sha256="a"*64)
        job = self.repo.enqueue(principal, document_id=doc, module="cv_formatting", idempotency_key=str(uuid4()))
        with self.repo.scoped(principal) as (conn, tenant, owner):
            conn.execute("""UPDATE cvcloud.jobs SET created_at=statement_timestamp()-interval '5 seconds'
                WHERE tenant_id=%s AND owner_id=%s AND id=%s""", (tenant, owner, job))
        self.assertGreaterEqual(self.repo.job(principal, job, include_elapsed=True)[4], 5000)
        self.assertIsNone(self.repo.job(other, job, include_elapsed=True))
        with self.repo.scoped(principal) as (conn, tenant, owner):
            conn.execute("""UPDATE cvcloud.jobs SET state='needs_review', updated_at=created_at+interval '2.5 seconds'
                WHERE tenant_id=%s AND owner_id=%s AND id=%s""", (tenant, owner, job))
        self.assertEqual(self.repo.job(principal, job, include_elapsed=True)[4], 2500)

    def test_fenced_worker_lifecycle(self):
        from cloud.worker_leases import WorkerLeases, Lease
        a,b=self.principals
        doc=self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64)
        job=self.repo.enqueue(a,document_id=doc,module="cv_blinding",idempotency_key=str(uuid4()))
        worker=WorkerLeases(self.repo)
        self.assertIsNone(worker.claim(b))
        lease=worker.claim(a)
        self.assertEqual(lease.job_id,job)
        self.assertIsNone(worker.claim(a))
        self.assertFalse(worker.heartbeat(b,lease))
        self.assertFalse(worker.finish(a,Lease(lease.job_id,lease.document_id,lease.module,str(uuid4())),"succeeded"))
        self.assertTrue(worker.heartbeat(a,lease))
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.jobs SET lease_until=now()-interval '1 second' WHERE tenant_id=%s AND id=%s",(a.tenant_id,job))
        self.assertFalse(worker.finish(a,lease,"succeeded"))
        self.assertEqual(worker.expire(a),1)
        self.assertEqual(self.repo.job(a,job)[2],"needs_review")
        self.assertIsNone(worker.claim(a))

    def test_cv_claim_filter_and_concurrent_owner_admission(self):
        from concurrent.futures import ThreadPoolExecutor
        from cloud.worker_leases import WorkerLeases
        a,b=self.principals
        doc=self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64)
        scoring=self.repo.enqueue(a,document_id=doc,module="cv_scoring",idempotency_key=str(uuid4()))
        jobs=[self.repo.enqueue(a,document_id=doc,module="cv_formatting",idempotency_key=str(uuid4())) for _ in range(2)]
        workers=WorkerLeases(self.repo)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims=list(pool.map(lambda _:workers.claim(a,cv_only=True),range(2)))
        won=[lease for lease in claims if lease is not None]
        self.assertEqual(len(won),1)
        self.assertIn(won[0].job_id,jobs)
        self.assertEqual(self.repo.job(a,scoring)[2],"queued")
        self.assertIsNone(workers.claim(b,cv_only=True))
        self.assertTrue(workers.finish(a,won[0],"needs_review"))
        second=workers.claim(a,cv_only=True)
        self.assertIsNotNone(second)
        self.assertNotEqual(second.job_id,won[0].job_id)
        self.assertTrue(workers.finish(a,second,"needs_review"))
        self.assertIsNone(workers.claim(a,cv_only=True))
        self.assertEqual(self.repo.job(a,scoring)[2],"queued")

    def test_provider_config_authorization_rotation_and_dispatch_fence(self):
        from cloud.provider_config import ProviderConfig,ProviderCatalogue,ProviderConfigError
        from cloud.ai_secrets import SecretCipher
        from cloud.ai_dispatch import ModelPolicy,Completion
        from cloud.auth import Principal
        a,b=self.principals
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='admin' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        admin=Principal(a.tenant_id,a.user_id,"admin",a.csrf)
        policy=ModelPolicy("deepseek","synthetic-model",100,200,4096,1024)
        calls=[]
        def factory(secret):
            def send(provider,model,system,prompt,limit):
                calls.append(secret)
                return Completion("{}",1,1)
            return send
        config=ProviderConfig(self.repo,SecretCipher({"test":b"x"*32},"test"),ProviderCatalogue([policy]),transport_factory=factory)
        forged=Principal(b.tenant_id,b.user_id,"admin",b.csrf)
        args=dict(provider="deepseek",model="synthetic-model",secret="synthetic-secret-one",expected_revision=0)
        with self.assertRaises(ProviderConfigError):
            config.configure(forged,**args)
        self.assertEqual(config.configure(admin,**args).revision,1)
        with self.assertRaises(ProviderConfigError):
            config.configure(admin,**args)
        with self.assertRaises(ProviderConfigError):
            config.resolve(b)
        with self.assertRaises(ProviderConfigError):
            config.status(b)
        self.assertNotIn("secret",repr(config.status(admin)))
        with psycopg.connect(DSN) as conn:
            stored=conn.execute("SELECT ciphertext FROM cvcloud.provider_config WHERE tenant_id=%s",(a.tenant_id,)).fetchone()[0]
            self.assertNotIn(b"synthetic-secret-one",stored)
        with self.repo.scoped(b) as (conn,tenant,user):
            self.assertEqual(conn.execute("SELECT count(*) FROM cvcloud.provider_config").fetchone()[0],0)
        selected,send=config.resolve(admin)
        self.assertEqual(selected,policy)
        self.assertEqual(calls,[])
        self.assertEqual(send("deepseek","synthetic-model","system","fixture",10).text,"{}")
        self.assertEqual(calls,["synthetic-secret-one"])
        rotated=config.configure(admin,**dict(args,secret="synthetic-secret-two",expected_revision=1))
        self.assertEqual(rotated.revision,2)
        with self.assertRaises(ProviderConfigError):
            send("deepseek","synthetic-model","system","fixture",10)
        _,new_send=config.resolve(admin)
        self.assertEqual(new_send("deepseek","synthetic-model","system","fixture",10).text,"{}")
        self.assertEqual(calls,["synthetic-secret-one","synthetic-secret-two"])
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='recruiter' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        with self.assertRaises(ProviderConfigError):
            config.disable(admin,expected_revision=2)
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='admin' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        self.assertFalse(config.disable(admin,expected_revision=2).enabled)
        with self.assertRaises(ProviderConfigError):
            config.resolve(admin)
        with self.assertRaises(ProviderConfigError):
            new_send("deepseek","synthetic-model","system","fixture",10)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("SELECT revision,key_version,nonce,ciphertext FROM cvcloud.provider_config WHERE tenant_id=%s",(a.tenant_id,)).fetchone(),(3,None,None,None))

    def test_ai_budget_atomic_and_fenced(self):
        from cloud.ai_budget import AIBudget,BudgetDenied
        from cloud.worker_leases import WorkerLeases
        a,b=self.principals
        with psycopg.connect(DSN) as conn:
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,100)",(a.tenant_id,))
        doc=self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64)
        self.repo.enqueue(a,document_id=doc,module="cv_formatting",idempotency_key=str(uuid4()))
        worker=WorkerLeases(self.repo)
        lease=worker.claim(a)
        ledger=AIBudget(self.repo)
        operation=str(uuid4())
        args=dict(operation_id=operation,provider="deepseek",model="deepseek-chat",estimated_microusd=60)
        with self.assertRaises(BudgetDenied):
            ledger.reserve(b,lease,**args)
        self.assertEqual(ledger.reserve(a,lease,**args).amount_microusd,60)
        with self.assertRaises(BudgetDenied):
            ledger.reserve(a,lease,**args)
        with self.assertRaises(BudgetDenied):
            ledger.reserve(a,lease,**dict(args,operation_id=str(uuid4())))
        # Even a smaller operation cannot dispatch while billing is unresolved.
        with self.assertRaises(BudgetDenied):
            ledger.reserve(a,lease,**dict(args,operation_id=str(uuid4()),estimated_microusd=1))
        self.assertFalse(worker.finish(a,lease,"succeeded"))
        self.assertFalse(worker.finish(a,lease,"failed"))
        self.assertTrue(ledger.settle(a,lease,operation_id=operation,actual_microusd=30))
        self.assertFalse(ledger.settle(a,lease,operation_id=operation,actual_microusd=30))
        with self.assertRaises(BudgetDenied):
            ledger.settle(a,lease,operation_id=operation,actual_microusd=31)
        second=str(uuid4())
        ledger.reserve(a,lease,**dict(args,operation_id=second))
        self.assertTrue(ledger.settle(a,lease,operation_id=second,actual_microusd=80))
        with self.assertRaises(BudgetDenied):
            ledger.reserve(a,lease,**dict(args,operation_id=str(uuid4())))
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM cvcloud.ai_budgets").fetchone()[0],0)
        with psycopg.connect(DSN) as conn:
            self.assertEqual(conn.execute("SELECT reserved_microusd,spent_microusd FROM cvcloud.ai_budgets WHERE tenant_id=%s",(a.tenant_id,)).fetchone(),(0,110))

    def test_stale_password_check_cannot_create_session(self):
        tenant,user,slug=self.ids[0]
        store=PostgresAuthStore(self.connect)
        checked=store.find_account(slug,"synthetic@example.test")
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.tenants SET active=false WHERE id=%s",(tenant,))
            conn.execute("UPDATE cvcloud.tenants SET active=true WHERE id=%s",(tenant,))
        from datetime import timedelta
        from cloud.auth import digest
        self.assertFalse(store.create_session(digest("old-session"),"synthetic",checked,datetime.now(timezone.utc)+timedelta(hours=1)))
        checked=store.find_account(slug,"synthetic@example.test")
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET active=false WHERE tenant_id=%s AND id=%s",(tenant,user))
            conn.execute("UPDATE cvcloud.users SET active=true WHERE tenant_id=%s AND id=%s",(tenant,user))
        self.assertFalse(store.create_session(digest("old-session"),"synthetic",checked,datetime.now(timezone.utc)+timedelta(hours=1)))

    def test_private_output_publication(self):
        import io,tempfile,zipfile
        from cloud.job_outputs import JobOutputs,OutputError
        from cloud.private_storage import PrivateStorage
        from cloud.worker_leases import WorkerLeases,Lease
        from cloud.cv_engine import Result
        a,b=self.principals
        doc=self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64)
        job=self.repo.enqueue(a,document_id=doc,module="cv_blinding",idempotency_key=str(uuid4()))
        workers=WorkerLeases(self.repo)
        lease=workers.claim(a)
        self.assertFalse(workers.finish(a,lease,"succeeded"))
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            for name in ("[Content_Types].xml","word/document.xml","_rels/.rels"):
                z.writestr(name,"<fixture/>")
        raw=buf.getvalue()
        with tempfile.TemporaryDirectory() as folder:
            outputs=JobOutputs(self.repo,PrivateStorage(folder))
            with self.assertRaises(OutputError):
                outputs.publish(b,lease,Result(raw,False,()))
            with self.assertRaises(OutputError):
                outputs.publish(a,Lease(lease.job_id,lease.document_id,lease.module,str(uuid4())),Result(raw,False,()))
            outputs.publish(a,lease,Result(raw,False,()))
            self.assertEqual(self.repo.job(a,job)[2],"needs_review")
            self.assertEqual(outputs.download(a,job).document,raw)
            self.assertTrue(outputs.download(a,job).requires_review)
            self.assertIsNone(outputs.download(b,job))
            with self.assertRaises(OutputError):
                outputs.publish(a,lease,Result(raw,False,()))

    def test_authenticated_cv_vertical_slice(self):
        import io,json,tempfile,zipfile
        from cloud.app import create_app,COOKIE
        from cloud.private_storage import PrivateStorage
        from cloud.upload_service import UploadService
        from cloud.job_outputs import JobOutputs
        from cloud.worker_leases import WorkerLeases
        from cloud.ai_budget import AIBudget
        from cloud.ai_dispatch import Completion,ModelPolicy
        from cloud.cv_runner import run_claimed
        a,b=self.principals
        origin="https://cv.example.test"
        fixtures=Path(__file__).with_name("fixtures")
        source=(fixtures/"cloud_cv_source.txt").read_bytes()
        parsed=(fixtures/"cloud_cv_parse.json").read_text(encoding="utf-8")
        with psycopg.connect(DSN) as conn:
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,1000000)",(a.tenant_id,))
        with tempfile.TemporaryDirectory() as folder:
            storage=PrivateStorage(folder)
            outputs=JobOutputs(self.repo,storage)
            uploads=UploadService(self.repo,storage)
            app=create_app(auth_store=PostgresAuthStore(self.connect),public_origin=origin,cv_services=(uploads,self.repo,outputs))
            client,other=app.test_client(),app.test_client()
            client.set_cookie(COOKIE,self.tokens[0],domain="cv.example.test",secure=True)
            other.set_cookie(COOKIE,self.tokens[1],domain="cv.example.test",secure=True)
            headers={"Origin":origin,"X-CSRF-Token":a.csrf}
            upload=client.post("/api/documents",base_url=origin,headers=headers,data=source,content_type="text/plain")
            self.assertEqual(upload.status_code,201)
            doc=upload.json["document_id"]
            key=str(uuid4())
            body={"document_id":doc,"module":"cv_formatting","idempotency_key":key,"alignment":"justify"}
            queued=client.post("/api/jobs",base_url=origin,headers=headers,json=body)
            self.assertEqual(queued.status_code,202)
            job=queued.json["job_id"]
            self.assertEqual(client.post("/api/jobs",base_url=origin,headers=headers,json=body).json["job_id"],job)
            self.assertEqual(client.post("/api/jobs",base_url=origin,headers=headers,json=dict(body,alignment="left")).status_code,409)
            self.assertEqual(other.get("/api/jobs/"+job,base_url=origin).status_code,404)
            self.assertEqual(other.post("/api/jobs",base_url=origin,headers={"Origin":origin,"X-CSRF-Token":b.csrf},json=body).status_code,404)
            workers=WorkerLeases(self.repo)
            lease=workers.claim(a)
            calls=[]
            def fake(provider,model,system,user,limit):
                calls.append(1)
                self.assertNotIn("9,000",user)
                return Completion(parsed,100,100)
            policy=ModelPolicy("deepseek","synthetic-model",1000000,1000000,100000,1000)
            self.assertTrue(run_claimed(principal=a,lease=lease,repository=self.repo,storage=storage,workers=workers,
                ledger=AIBudget(self.repo),policy=policy,transport=fake,outputs=outputs))
            self.assertEqual(calls,[1])
            status=client.get("/api/jobs/"+job,base_url=origin).json["state"]
            self.assertIn(status,("succeeded","needs_review"))
            download=client.get("/api/jobs/"+job+"/download?review=1",base_url=origin)
            self.assertEqual(download.status_code,200)
            self.assertEqual(other.get("/api/jobs/"+job+"/download?review=1",base_url=origin).status_code,404)
            with zipfile.ZipFile(io.BytesIO(download.data)) as z:
                xml=z.read("word/document.xml").decode()
            self.assertIn("Disaster Recovery Automation",xml)
            self.assertIn('w:val="both"',xml)
            self.assertNotIn("9,000",xml)

    def test_synthetic_staging_composition(self):
        import io,tempfile,zipfile
        from cloud.staging import compose_synthetic
        a,b=self.principals
        origin="https://cv.example.test"
        fixtures=Path(__file__).with_name("fixtures")
        source=(fixtures/"cloud_cv_source.txt").read_text(encoding="utf-8")
        parsed=(fixtures/"cloud_cv_parse.json").read_text(encoding="utf-8")
        with psycopg.connect(DSN) as conn:
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,1000000)",(a.tenant_id,))
        with tempfile.TemporaryDirectory() as folder:
            env=compose_synthetic(connect=self.connect,storage_root=folder,principals=[a],public_origin=origin,
                fixture_source=source,fixture_answer=parsed)
            client,other=env.app.test_client(),env.app.test_client()
            page=client.get("/cloud-ui",base_url=origin)
            self.assertEqual(page.status_code,200)
            self.assertIn(b'id="btnFormat"',page.data)
            self.assertNotIn(b'id="tabJobLeads"',page.data)
            self.assertEqual(client.get("/readyz",base_url=origin).status_code,503)
            self.assertEqual(client.get("/api/auth/me",base_url=origin).status_code,401)
            login=client.post("/api/auth/login",base_url=origin,headers={"Origin":origin},
                json={"tenant":self.ids[0][2],"email":"synthetic@example.test","password":"synthetic-password-123"})
            self.assertEqual(login.status_code,200)
            session=client.get("/api/auth/me",base_url=origin).json
            headers={"Origin":origin,"X-CSRF-Token":session["csrf"]}
            self.assertEqual(client.post("/api/documents",base_url=origin,data=source.encode(),content_type="text/plain").status_code,403)
            uploaded=client.post("/api/documents",base_url=origin,headers=headers,data=source.encode(),content_type="text/plain")
            self.assertEqual(uploaded.status_code,201)
            job=client.post("/api/jobs",base_url=origin,headers=headers,json={"document_id":uploaded.json["document_id"],
                "module":"cv_formatting","idempotency_key":str(uuid4()),"alignment":"justify"})
            self.assertEqual(job.status_code,202)
            url="/api/jobs/"+job.json["job_id"]
            self.assertEqual(client.get(url,base_url=origin).json["state"],"queued")
            self.assertEqual(env.worker.tick(),("completed",))
            result=client.get(url+"/download?review=1",base_url=origin)
            self.assertEqual(result.status_code,200)
            with zipfile.ZipFile(io.BytesIO(result.data)) as z:
                xml=z.read("word/document.xml").decode()
            self.assertIn("Disaster Recovery Automation",xml)
            self.assertNotIn("9,000",xml)
            login=other.post("/api/auth/login",base_url=origin,headers={"Origin":origin},
                json={"tenant":self.ids[1][2],"email":"synthetic@example.test","password":"synthetic-password-123"})
            self.assertEqual(login.status_code,200)
            self.assertEqual(other.get(url,base_url=origin).status_code,404)
            self.assertEqual(other.get(url+"/download?review=1",base_url=origin).status_code,404)
            self.assertEqual(client.post("/api/auth/logout",base_url=origin,headers=headers).status_code,200)
            self.assertEqual(client.get(url,base_url=origin).status_code,401)
            self.assertEqual(env.worker.tick(),("idle",))

    @unittest.skipUnless(os.environ.get("CVCLOUD_REQUIRE_BROWSER")=="1","Explicit browser fixture required")
    def test_original_browser_cv_workflow(self):
        import tempfile,zipfile
        from urllib.parse import urlsplit
        from playwright.sync_api import sync_playwright,expect
        from cloud.staging import compose_synthetic
        a,b=self.principals
        origin="https://cv.example.test"
        fixtures=Path(__file__).with_name("fixtures")
        source=(fixtures/"cloud_cv_source.txt").read_text(encoding="utf-8")
        parsed=(fixtures/"cloud_cv_parse.json").read_text(encoding="utf-8")
        with psycopg.connect(DSN) as conn:
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,1000000)",(a.tenant_id,))
        with tempfile.TemporaryDirectory() as folder, sync_playwright() as pw:
            env=compose_synthetic(connect=self.connect,storage_root=folder,principals=[a],public_origin=origin,
                fixture_source=source,fixture_answer=parsed,enable_batch=True)
            browser=pw.chromium.launch()
            context=browser.new_context(accept_downloads=True)
            page=context.new_page()
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            # Real Chromium executes original markup and cloud JavaScript.
            # All requests are intercepted and delivered to the actual Flask
            # application with browser headers; no external network or live AI.
            http=env.app.test_client(use_cookies=False)
            seen=[]
            def respond(route):
                req=route.request
                url=urlsplit(req.url)
                if (url.scheme,url.netloc)!=("https","cv.example.test"):
                    route.abort()
                    return
                path=url.path+("?" + url.query if url.query else "")
                headers={k:v for k,v in req.all_headers().items() if k.lower() not in ("host","content-length")}
                response=http.open(path,method=req.method,base_url=origin,headers=headers,data=req.post_data_buffer)
                seen.append((req.method,url.path,response.status_code))
                body=response.get_data()
                hdr=dict(response.headers)
                hdr.pop("Content-Length",None)
                route.fulfill(status=response.status_code,headers=hdr,body=body)
                response.close()
            context.route("**/*",respond)
            try:
                page.goto(origin+"/cloud-ui")
                expect(page.locator("#cloudLoginPanel")).to_be_visible()
                expect(page.locator("#cloudContent")).to_be_hidden()
                page.locator('[name="tenant"]').fill(self.ids[0][2])
                page.locator('[name="email"]').fill("synthetic@example.test")
                page.locator('[name="password"]').fill("synthetic-password-123")
                page.locator("#cloudLogin button").click()
                expect(page.locator("#cloudContent")).to_be_visible()
                expect(page.locator("#cloudLoginPanel")).to_be_hidden()
                expect(page.locator("#btnFormat")).to_be_enabled()
                expect(page.locator("#tabBatch")).to_be_enabled()
                assert page.locator("#tabJobLeads").count()==0
                page.locator("#cvInput").fill(source)
                page.locator("#cloudAlignment").select_option("justify")
                page.locator("#btnFormat").click()
                expect(page.locator("#stepText")).to_contain_text("Queued")
                self.assertEqual(env.worker.tick(),("completed",))
                page.locator("#cloudRefresh").click()
                expect(page.locator("#btnDocx")).to_be_enabled()
                page.on("dialog",lambda dialog:dialog.accept())
                with page.expect_download() as pending:
                    page.locator("#btnDocx").click()
                download=pending.value
                self.assertTrue(download.suggested_filename.endswith(".docx"))
                with zipfile.ZipFile(download.path()) as z:
                    xml=z.read("word/document.xml").decode()
                self.assertIn("Disaster Recovery Automation",xml)
                self.assertNotIn("9,000",xml)
                self.assertIn(('POST','/api/documents',201),seen)
                self.assertIn(('POST','/api/jobs',202),seen)
                page.locator("#tabBatch").click()
                expect(page.locator("#viewBatch")).to_be_visible()
                page.locator("#batchFileInput").set_input_files([
                    {"name":"duplicate.txt","mimeType":"text/plain","buffer":source.encode()},
                    {"name":"duplicate.txt","mimeType":"text/plain","buffer":source.encode()}])
                expect(page.locator("#batchFileList .batch-file-item")).to_have_count(2)
                page.locator("#btnBatchRun").click()
                expect(page.locator("#batchFileList")).to_contain_text("Queued")
                # Both admissions must finish before ticking the worker.
                expect(page.locator("#batchFileList")).not_to_contain_text("Ready")
                expect(page.locator("#batchFileList")).not_to_contain_text("Submitting")
                expect(page.locator("#batchFileList")).not_to_contain_text("Uploading")
                self.assertEqual(env.worker.tick(),("completed",))
                self.assertEqual(env.worker.tick(),("completed",))
                expect(page.locator("#batchSummary")).to_have_text("2 / 2 finished",timeout=15000)
                with page.expect_download() as batch_download:
                    page.locator("#batchFileList button").first.click()
                self.assertTrue(batch_download.value.suggested_filename.startswith("cv-01"))
                with page.expect_download(lambda item: item.suggested_filename.startswith("cv-01")) as first:
                    with page.expect_download(lambda item: item.suggested_filename.startswith("cv-02")) as second:
                        page.locator("#btnBatchDownload").click()
                self.assertTrue(first.value.suggested_filename.endswith(".docx"))
                self.assertTrue(second.value.suggested_filename.endswith(".docx"))
                expect(page.locator("#batchSummary")).to_contain_text("2 / 2 downloads started.")
                page.locator("#cloudLogout").click()
                expect(page.locator("#cloudLoginPanel")).to_be_visible()
                expect(page.locator("#batchFileList .batch-file-item")).to_have_count(0)
                expect(page.locator("#cloudContent")).to_be_hidden()
                self.assertEqual(page.locator("#cvInput").input_value(),"")
                self.assertEqual(page.evaluate("localStorage.length"),0)
                self.assertEqual(page.evaluate("sessionStorage.length"),0)
                page.locator('[name="tenant"]').fill(self.ids[0][2])
                page.locator('[name="email"]').fill("synthetic@example.test")
                page.locator('[name="password"]').fill("synthetic-password-123")
                page.locator("#cloudLogin button").click()
                expect(page.locator("#cloudHistoryToggle")).to_be_visible()
                page.locator("#cloudHistoryToggle").click()
                expect(page.locator("#cloudHistoryList .batch-file-item")).to_have_count(3)
                with page.expect_download() as previous:
                    page.locator("#cloudHistoryList button",has_text="Download DOCX").first.click()
                self.assertTrue(previous.value.suggested_filename.endswith(".docx"))
                page.locator("#cloudHistoryDocuments").click()
                expect(page.locator("#cloudHistoryList .batch-file-item")).to_have_count(3)
                page.locator("#cloudHistoryClose").click()
                self.assertEqual(page.locator("#cloudHistoryList").inner_text(),"")
                page.locator("#cloudLogout").click()
                expect(page.locator("#cloudLoginPanel")).to_be_visible()
                self.assertFalse(errors,errors)
            finally:
                context.close()
                browser.close()

    def test_owner_history_pagination_and_isolation(self):
        from cloud.job_options import Options
        a,b=self.principals
        docs=[self.repo.register_document(a,media_type="text/plain",byte_size=10,sha256="a"*64) for _ in range(3)]
        other=self.repo.register_document(b,media_type="text/plain",byte_size=10,sha256="b"*64)
        jobs=[self.repo.enqueue(a,document_id=d,module="cv_formatting",idempotency_key=str(uuid4()),options=Options()) for d in docs[:2]]
        self.repo.enqueue(a,document_id=docs[0],module="cv_scoring",idempotency_key=str(uuid4()))
        first=self.repo.history(a,kind="documents",limit=2)
        self.assertEqual(len(first["items"]),2)
        self.assertIsNotNone(first["next_cursor"])
        second=self.repo.history(a,kind="documents",limit=2,before=first["next_cursor"])
        self.assertIsNone(second["next_cursor"])
        all_docs=first["items"]+second["items"]
        self.assertEqual({x["document_id"] for x in all_docs},set(docs))
        self.assertFalse(next(x for x in all_docs if x["document_id"]==docs[2])["has_jobs"])
        first=self.repo.history(a,kind="jobs",limit=1)
        second=self.repo.history(a,kind="jobs",limit=1,before=first["next_cursor"])
        self.assertEqual({x["job_id"] for x in first["items"]+second["items"]},set(jobs))
        self.assertIsNone(second["next_cursor"])
        self.assertFalse(first["items"][0]["output_available"])
        self.assertEqual(self.repo.history(b,kind="jobs")["items"],[])
        with self.assertRaises(ScopeError):
            self.repo.history(a,kind="documents",before=other)
        with self.assertRaises(ScopeError):
            self.repo.history(b,kind="jobs",before=jobs[0])

    def test_account_administration_scope_and_revocation(self):
        from cloud.account_admin import AccountAdmin,AccountAdminError
        from cloud.auth import Principal
        a,b=self.principals
        service=AccountAdmin(self.repo)
        with self.assertRaises(AccountAdminError):
            service.list_accounts(a)
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='owner' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        # Stale cached recruiter role cannot grant authority; the service reads actual role.
        owner=Principal(a.tenant_id,a.user_id,"owner",a.csrf)
        new=service.create(owner,email="  New@Example.TEST ",role="recruiter",password="fictional-password-123")
        self.assertEqual(new.email,"new@example.test")
        self.assertEqual(new.revision,1)
        self.assertNotIn("fictional-password",repr(new))
        with self.assertRaises(AccountAdminError):
            service.create(owner,email=new.email,role="recruiter",password="fictional-password-123")
        with self.assertRaises(AccountAdminError):
            service.create(owner,email="other@example.test",role="owner",password="fictional-password-123")
        with self.assertRaises(AccountAdminError):
            service.change(owner,user_id=b.user_id,expected_revision=1,action="suspend")
        with self.assertRaises(AccountAdminError):
            service.change(owner,user_id=a.user_id,expected_revision=2,action="suspend")
        slug=self.ids[0][2]
        raw=self.auth.login(slug,new.email,"fictional-password-123","account-fixture")
        self.assertIsNotNone(self.auth.principal(raw))
        promoted=service.change(owner,user_id=new.user_id,expected_revision=1,action="role_change",value="admin")
        self.assertEqual(promoted.revision,2)
        self.assertIsNone(self.auth.principal(raw))
        raw=self.auth.login(slug,new.email,"fictional-password-123","account-fixture")
        admin=self.auth.principal(raw)
        self.assertEqual(admin.role,"admin")
        with self.assertRaises(AccountAdminError):
            service.create(admin,email="no@example.test",role="admin",password="fictional-password-123")
        with self.assertRaises(AccountAdminError):
            service.change(owner,user_id=new.user_id,expected_revision=1,action="suspend")
        reset=service.change(owner,user_id=new.user_id,expected_revision=2,action="password_reset",value="another-fictional-password")
        self.assertIsNone(self.auth.principal(raw))
        raw=self.auth.login(slug,new.email,"another-fictional-password","account-fixture")
        suspended=service.change(owner,user_id=new.user_id,expected_revision=reset.revision,action="suspend")
        self.assertFalse(suspended.active)
        self.assertIsNone(self.auth.principal(raw))
        enabled=service.change(owner,user_id=new.user_id,expected_revision=suspended.revision,action="reactivate")
        self.assertTrue(enabled.active)
        self.assertIsNone(self.auth.principal(raw))
        raw=self.auth.login(slug,new.email,"another-fictional-password","account-fixture")
        self.assertIsNotNone(self.auth.principal(raw))
        service.change(owner,user_id=new.user_id,expected_revision=enabled.revision,action="revoke_sessions")
        self.assertIsNone(self.auth.principal(raw))
        self.assertEqual({x.user_id for x in service.list_accounts(owner)},{a.user_id,new.user_id})
        with self.repo.scoped(owner) as (conn,tenant,user):
            actions={x[0] for x in conn.execute("SELECT action FROM cvcloud.account_audit").fetchall()}
            self.assertEqual(actions,{"create","role_change","password_reset","suspend","reactivate","revoke_sessions"})
            self.assertEqual(conn.execute("DELETE FROM cvcloud.account_audit").rowcount,0)
        with self.repo.scoped(b) as (conn,tenant,user):
            self.assertEqual(conn.execute("SELECT count(*) FROM cvcloud.account_audit").fetchone()[0],0)

    def test_account_admin_http_boundary(self):
        from cloud.account_admin import AccountAdmin
        from cloud.app import create_app,COOKIE
        a,b=self.principals
        service=AccountAdmin(self.repo)
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='owner' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        raw=self.auth.login(self.ids[0][2],"synthetic@example.test","synthetic-password-123","account-http-fixture")
        owner=self.auth.principal(raw)
        target=service.create(owner,email="target@example.test",role="recruiter",password="fictional-password-123")
        target_raw=self.auth.login(self.ids[0][2],target.email,"fictional-password-123","account-http-target")
        origin="https://cv.example.test"
        app=create_app(auth_store=PostgresAuthStore(self.connect),public_origin=origin,account_admin=service)
        client=app.test_client()
        other=app.test_client()
        client.set_cookie(COOKIE,raw,domain="cv.example.test",secure=True)
        other.set_cookie(COOKIE,self.tokens[1],domain="cv.example.test",secure=True)
        url="/api/admin/accounts"
        response=client.get(url,base_url=origin)
        self.assertEqual(response.status_code,200)
        self.assertEqual({x["user_id"] for x in response.json["items"]},{owner.user_id,target.user_id})
        self.assertEqual(other.get(url,base_url=origin).status_code,403)
        headers={"Origin":origin,"X-CSRF-Token":owner.csrf}
        action=url+"/"+target.user_id+"/actions"
        payload={"action":"suspend","expected_revision":"1"}
        self.assertEqual(client.post(action,base_url=origin,json=payload).status_code,403)
        self.assertEqual(client.post(url+"/"+b.user_id+"/actions",base_url=origin,headers=headers,json=payload).status_code,403)
        result=client.post(action,base_url=origin,headers=headers,json=payload)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json["account"]["revision"],"2")
        self.assertFalse(result.json["account"]["active"])
        self.assertIsNone(self.auth.principal(target_raw))
        self.assertEqual(client.post(action,base_url=origin,headers=headers,json=payload).status_code,409)
        self.assertEqual(client.post(action,base_url=origin,headers=headers,json={"action":"password_reset","expected_revision":"2","value":"fictional"}).status_code,400)

    def test_admin_ai_usage_isolation(self):
        from cloud.ai_usage import AIUsage
        from cloud.app import create_app,COOKIE
        a,b=self.principals
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='owner' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
            conn.execute("UPDATE cvcloud.users SET role='admin' WHERE tenant_id=%s AND id=%s",(b.tenant_id,b.user_id))
            conn.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd,reserved_microusd,spent_microusd) VALUES (%s,1000000,200000,300000)",(a.tenant_id,))
        ra=self.auth.login(self.ids[0][2],"synthetic@example.test","synthetic-password-123","usage-fixture-a")
        rb=self.auth.login(self.ids[1][2],"synthetic@example.test","synthetic-password-123","usage-fixture-b")
        origin="https://cv.example.test"
        app=create_app(auth_store=PostgresAuthStore(self.connect),public_origin=origin,ai_usage=AIUsage(self.repo))
        ca,cb=app.test_client(),app.test_client()
        ca.set_cookie(COOKIE,ra,domain="cv.example.test",secure=True)
        cb.set_cookie(COOKIE,rb,domain="cv.example.test",secure=True)
        url="/api/admin/ai-usage"
        response=ca.get(url,base_url=origin)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json["remaining_microusd"],"500000")
        self.assertEqual(response.json["spent_microusd"],"300000")
        self.assertEqual(cb.get(url,base_url=origin).json,{"configured":False})
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.ai_budgets SET spent_microusd=1100000 WHERE tenant_id=%s",(a.tenant_id,))
        response=ca.get(url,base_url=origin)
        self.assertEqual(response.json["remaining_microusd"],"0")
        self.assertEqual(response.json["over_limit_microusd"],"300000")
        self.assertEqual(ca.get(url+"?tenant_id="+b.tenant_id,base_url=origin).status_code,400)

    def test_one_time_onboarding_lifecycle(self):
        from cloud.account_onboarding import AccountOnboarding
        from cloud.account_admin import AccountAdmin,AccountAdminError
        from cloud.auth import digest
        from datetime import timedelta
        from concurrent.futures import ThreadPoolExecutor
        a,b=self.principals
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET role='owner' WHERE tenant_id=%s AND id=%s",(a.tenant_id,a.user_id))
        owner=self.auth.principal(self.auth.login(self.ids[0][2],"synthetic@example.test","synthetic-password-123","onboard-owner"))
        now=[datetime.now(timezone.utc)]
        service=AccountOnboarding(self.repo,clock=lambda:now[0])
        admin=AccountAdmin(self.repo)
        with self.assertRaises(AccountAdminError):
            service.invite(b,email="denied@example.test",role="recruiter")
        invite=service.invite(owner,email="new@example.test",role="recruiter")
        self.assertNotIn(invite.token,repr(invite))
        with psycopg.connect(DSN) as conn:
            row=conn.execute("SELECT token_digest FROM cvcloud.account_challenges WHERE user_id=%s",(invite.user_id,)).fetchone()
            self.assertEqual(row[0],digest(invite.token))
            self.assertFalse(conn.execute("SELECT active FROM cvcloud.users WHERE id=%s",(invite.user_id,)).fetchone()[0])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:service.redeem(invite.token,"fictional-password-new"),range(2)))
        self.assertEqual(sorted(results),[False,True])
        self.assertFalse(service.redeem(invite.token,"fictional-password-new"))
        raw=self.auth.login(self.ids[0][2],"new@example.test","fictional-password-new","onboard-target")
        self.assertIsNotNone(self.auth.principal(raw))
        target=next(x for x in admin.list_accounts(owner) if x.user_id==invite.user_id)
        reset=service.reset(owner,user_id=target.user_id,expected_revision=target.revision)
        self.assertIsNone(self.auth.principal(raw))
        self.assertIsNone(self.auth.login(self.ids[0][2],"new@example.test","fictional-password-new","onboard-target"))
        target=next(x for x in admin.list_accounts(owner) if x.user_id==invite.user_id)
        newer=service.reset(owner,user_id=target.user_id,expected_revision=target.revision)
        self.assertFalse(service.redeem(reset.token,"another-fictional-password"))
        self.assertTrue(service.redeem(newer.token,"another-fictional-password"))
        self.assertIsNotNone(self.auth.login(self.ids[0][2],"new@example.test","another-fictional-password","onboard-target"))
        target=next(x for x in admin.list_accounts(owner) if x.user_id==invite.user_id)
        blocked=service.reset(owner,user_id=target.user_id,expected_revision=target.revision)
        target=next(x for x in admin.list_accounts(owner) if x.user_id==invite.user_id)
        admin.change(owner,user_id=target.user_id,expected_revision=target.revision,action="suspend")
        self.assertFalse(service.redeem(blocked.token,"third-fictional-password"))
        expired=service.invite(owner,email="expired@example.test",role="recruiter")
        now[0]+=timedelta(hours=25)
        self.assertFalse(service.redeem(expired.token,"fictional-password-new"))
        from cloud.app import create_app
        expired_status=next(x for x in admin.list_accounts(owner) if x.user_id==expired.user_id)
        with self.assertRaises(AccountAdminError):
            admin.change(owner,user_id=expired.user_id,expected_revision=expired_status.revision,action="reactivate")
        replacement=service.reissue_invitation(owner,user_id=expired.user_id,expected_revision=expired_status.revision)
        with self.assertRaises(AccountAdminError):
            service.reissue_invitation(owner,user_id=expired.user_id,expected_revision=expired_status.revision)
        self.assertFalse(service.redeem(expired.token,"fictional-password-new"))
        app=create_app(auth_store=PostgresAuthStore(self.connect),public_origin="https://cv.example.test",onboarding=service)
        client=app.test_client()
        headers={"Origin":"https://cv.example.test"}
        payload={"token":replacement.token,"password":"fictional-password-new"}
        response=client.post("/api/auth/redeem",base_url="https://cv.example.test",headers=headers,json=payload)
        self.assertEqual(response.status_code,200)
        self.assertNotIn("Set-Cookie",response.headers)
        self.assertEqual(client.post("/api/auth/redeem",base_url="https://cv.example.test",headers=headers,json=payload).status_code,400)
        self.assertIsNotNone(self.auth.login(self.ids[0][2],"expired@example.test","fictional-password-new","onboard-expired"))


    def test_password_and_tenant_revocation(self):
        tenant,user,_=self.ids[0]
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.users SET password_hash=%s WHERE tenant_id=%s AND id=%s",(password_hash("changed-password-123"),tenant,user))
        self.assertIsNone(self.auth.principal(self.tokens[0]))
        tenant,_,_=self.ids[1]
        with psycopg.connect(DSN) as conn:
            conn.execute("UPDATE cvcloud.tenants SET active=false WHERE id=%s",(tenant,))
            conn.execute("UPDATE cvcloud.tenants SET active=true WHERE id=%s",(tenant,))
        self.assertIsNone(self.auth.principal(self.tokens[1]))

if __name__=="__main__":
    unittest.main()
