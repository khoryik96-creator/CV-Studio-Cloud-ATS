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
