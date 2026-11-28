"""Disposable Linux CI only. No live network/provider calls."""
import os
import unittest
from unittest.mock import patch

@unittest.skipUnless(os.environ.get("GITHUB_ACTIONS")=="true"
    and os.environ.get("RUNNER_OS")=="Linux" and os.environ.get("CVCLOUD_TEST_DSN"),
    "Disposable Linux CI PostgreSQL required")
class WorkspacePostgresTest(unittest.TestCase):
    def test_restricted_workspace(self):
        import io
        import secrets
        import tempfile
        from pathlib import Path
        from uuid import uuid4
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict,make_conninfo
        from cloud.auth import Principal
        from cloud.ai_budget import AIBudget
        from cloud.ai_dispatch import ModelPolicy,Completion
        from cloud.ai_secrets import SecretCipher
        from cloud.deploy import online_init
        from cloud.deploy.online_owner import provision_owner
        from cloud.deploy.online_workspace_schema import apply_workspace_schema
        from cloud.deploy.workspace_grant_install import ROLES,install_grants
        from cloud.deploy.workspace_repository import OnlineDocumentJobs
        from cloud.deploy.workspace_admin_install import ROLE as ADMIN_ROLE
        from tests.cloud_online_admin_acceptance import verify_admin_acceptance
        from cloud.deploy.workspace_roles import discover_roster
        from cloud.provider_config import ProviderCatalogue,ProviderConfig
        from cloud.private_storage import PrivateStorage
        from cloud.upload_service import UploadService
        from cloud.worker_leases import WorkerLeases

        dsn=os.environ["CVCLOUD_TEST_DSN"]
        parsed=conninfo_to_dict(dsn)
        self.assertEqual((parsed.get("host"),parsed.get("dbname")),("127.0.0.1","cvcloud_test"))
        credentials={r:secrets.token_hex(32) for r in (online_init.BOOT,online_init.OWNER,online_init.AUTH,*ROLES.values(),ADMIN_ROLE)}
        created_boot=created_db=False
        admin=psycopg.connect(dsn,autocommit=True)
        def connect(role,password=None):
            return psycopg.connect(make_conninfo(dsn,dbname="cvcloud_online",user=role,
                password=credentials[role] if password is None else password,connect_timeout=5,
                options="-c statement_timeout=15000 -c lock_timeout=5000"))
        try:
            self.assertIsNone(admin.execute("SELECT 1 FROM pg_database WHERE datname='cvcloud_online'").fetchone())
            self.assertIsNone(admin.execute("SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)",(list(credentials),)).fetchone())
            admin.execute(sql.SQL("CREATE ROLE cvcloud_bootstrap LOGIN SUPERUSER PASSWORD {}").format(sql.Literal(credentials[online_init.BOOT])))
            created_boot=True
            admin.execute("CREATE DATABASE cvcloud_online OWNER cvcloud_bootstrap")
            created_db=True
            with patch.object(online_init,"connect_as",side_effect=connect),patch.object(online_init,"read_secret",side_effect=[
                credentials[online_init.BOOT],credentials[online_init.OWNER],credentials[online_init.AUTH]]):
                online_init.initialize()
            owner=lambda:connect(online_init.OWNER)
            self.assertTrue(apply_workspace_schema(owner))
            self.assertFalse(apply_workspace_schema(owner))
            values={service:credentials[role] for service,role in ROLES.items()}
            for _ in range(2):
                install_grants(boot_connect=lambda:connect(online_init.BOOT),secrets=values,runtime_connect=connect)
            ids=[provision_owner(owner,tenant=t,email="owner@example.test",password="fictional-owner-password-123") for t in ("one","two")]
            a,b=[Principal(t,u,"owner","") for t,u in ids]
            self.assertEqual({(p.tenant_id,p.user_id) for p in discover_roster(lambda:connect(ROLES["scheduler"]))},set(ids))
            for role,statement in (
                (ROLES["document"],"UPDATE cvcloud.users SET active=false"),
                (ROLES["document"],"SELECT password_hash FROM cvcloud.users"),
                (ROLES["document"],"UPDATE cvcloud.jobs SET state='succeeded'"),
                (ROLES["worker"],"UPDATE cvcloud.ai_budgets SET limit_microusd=999"),
                (ROLES["worker"],"SELECT ciphertext FROM cvcloud.provider_config"),
                (ROLES["provider"],"SELECT ciphertext FROM cvcloud.provider_config"),
                (ROLES["provider_reader"],"UPDATE cvcloud.provider_config SET enabled=false"),
                (ROLES["scheduler"],"SELECT * FROM cvcloud.documents"),
                (ROLES["scheduler"],"SELECT * FROM cvcloud.users"),
            ):
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    with connect(role) as c:
                        c.execute(statement)
            with connect(ROLES["document"]) as c:
                self.assertEqual(c.execute("SELECT cvcloud.lock_workspace_account(true)").fetchone(),(None,))
                self.assertEqual(c.execute("SELECT count(*) FROM cvcloud.documents").fetchone(),(0,))
            verify_admin_acceptance(self,boot_connect=lambda:connect(online_init.BOOT),
                owner_connect=owner,admin_connect=lambda:connect(ADMIN_ROLE),
                auth_connect=lambda:connect(online_init.AUTH),
                password=credentials[ADMIN_ROLE],owner_a=a,owner_b=b)
            doc=OnlineDocumentJobs(lambda:connect(ROLES["document"]))
            worker=OnlineDocumentJobs(lambda:connect(ROLES["worker"]))
            writer=OnlineDocumentJobs(lambda:connect(ROLES["provider"]))
            reader=OnlineDocumentJobs(lambda:connect(ROLES["provider_reader"]))
            # Test budget explicitly configured by the disposable schema owner.
            with owner() as c:
                c.execute("SELECT set_config('cvcloud.tenant_id',%s,true)",(a.tenant_id,))
                c.execute("INSERT INTO cvcloud.ai_budgets (tenant_id,limit_microusd) VALUES (%s,100000)",(a.tenant_id,))
            cipher=SecretCipher({"test":secrets.token_bytes(32)},"test")
            policy=ModelPolicy("deepseek","fictional-model",100,200,200000,32000)
            catalogue=ProviderCatalogue([policy])
            web_config=ProviderConfig(writer,cipher,catalogue)
            self.assertTrue(web_config.configure(a,provider=policy.provider,model=policy.model,secret="fictional-key",expected_revision=0).enabled)
            self.assertEqual(web_config.status(a).model,policy.model)
            self.assertIsNone(web_config.status(b))
            def transport_factory(secret):
                self.assertEqual(secret,"fictional-key")
                return lambda *args:Completion("{}",1,1)
            read_config=ProviderConfig(reader,cipher,catalogue,transport_factory=transport_factory)
            selected,transport=read_config.resolve(a)
            self.assertEqual(selected,policy)
            self.assertEqual(transport(policy.provider,policy.model,"system","prompt",1).text,"{}")
            with tempfile.TemporaryDirectory() as tmp:
                # Exercise the actual online composition, not just independent services.
                from cloud.deploy.online_workspace import assemble_workspace
                from cloud.deploy.online_auth import OnlineAuthConfig
                app=assemble_workspace(config=OnlineAuthConfig("https://cvstudio.hyplug.co","127.0.0.1",credentials[online_init.AUTH]),
                    auth_connect=lambda:connect(online_init.AUTH),document_connect=lambda:connect(ROLES["document"]),
                    provider_connect=lambda:connect(ROLES["provider"]),admin_connect=lambda:connect(ADMIN_ROLE),storage_root=Path(tmp).resolve(),
                    cipher=cipher,catalogue=catalogue)
                with app.test_client() as client:
                    headers={"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https"}
                    self.assertEqual(client.get("/cloud-ui",base_url="https://cvstudio.hyplug.co",headers=headers).status_code,200)
                uploads=UploadService(doc,PrivateStorage(Path(tmp).resolve()))
                raw=b"Fictional candidate"
                document=uploads.upload(a,io.BytesIO(raw),media_type="text/plain",byte_size=len(raw))
                self.assertIsNone(doc.document(b,document))
                job=doc.enqueue(a,document_id=document,module="cv_formatting",idempotency_key=str(uuid4()))
                self.assertIsNone(doc.job(b,job))
                leases=WorkerLeases(worker)
                self.assertIsNone(leases.claim(b,cv_only=True))
                lease=leases.claim(a,cv_only=True)
                self.assertEqual(lease.job_id,job)
                self.assertTrue(leases.heartbeat(a,lease))
                ledger=AIBudget(worker)
                op=str(uuid4())
                ledger.reserve(a,lease,operation_id=op,provider=policy.provider,model=policy.model,estimated_microusd=10)
                self.assertTrue(ledger.settle(a,lease,operation_id=op,actual_microusd=5))
                self.assertTrue(leases.finish(a,lease,"failed"))
                self.assertEqual(doc.job(a,job)[2],"failed")
                self.assertEqual(doc.history(a,kind="jobs")["items"][0]["job_id"],job)
                from tests.cloud_online_worker_acceptance import verify_worker_acceptance
                verify_worker_acceptance(self,principal=a,other=b,storage_root=Path(tmp).resolve(),
                    document_connect=lambda:connect(ROLES["document"]),worker_connect=lambda:connect(ROLES["worker"]),
                    provider_connect=lambda:connect(ROLES["provider_reader"]),cipher=cipher,catalogue=catalogue,policy=policy)
            self.assertTrue(web_config.disable(a,expected_revision=1).enabled is False)
        finally:
            try:
                if created_db:
                    admin.execute("DROP DATABASE cvcloud_online WITH (FORCE)")
                    for role in credentials:
                        if role!=online_init.BOOT:
                            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
                if created_boot:
                    admin.execute("DROP ROLE cvcloud_bootstrap")
            finally:
                admin.close()
