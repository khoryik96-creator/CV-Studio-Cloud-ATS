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
