"""Disposable restricted PostgreSQL CRM attempt fencing checks; no network."""
from uuid import uuid4
from cloud.deploy.workspace_crm_journal import AttemptJournal
from cloud.jobadder_sandbox import CRMUnavailable
from cloud.worker_leases import WorkerLeases

def verify_crm_journal(test, *, principal, other, document_repository, worker_repository, document_id):
    settings={"account_id":"fictional-sandbox","revision":1,"environment":"sandbox"}
    confirmation={"sha256":"a"*64,"settings":settings}
    key=b"j"*32
    leases=WorkerLeases(worker_repository)
    def start():
        job=document_repository.enqueue(principal,document_id=document_id,module="create_profile",
            idempotency_key=str(uuid4()),profile=confirmation)
        lease=leases.claim(principal,cv_only=True,include_profile=True)
        test.assertEqual(lease.job_id,job)
        with worker_repository.scoped(principal) as (conn,tenant,user):
            conn.execute("UPDATE cvcloud.jobs SET profile_started_at=clock_timestamp() WHERE tenant_id=%s AND owner_id=%s AND id=%s",
                (tenant,user,job))
        return lease
    journal=AttemptJournal(worker_repository,key)
    first=start()
    with test.assertRaises(CRMUnavailable):
        with journal.guard(principal,settings["account_id"],first.job_id,"candidate@example.test",lease_token=str(uuid4())):
            test.fail("Wrong lease must not dispatch")
    with test.assertRaises(CRMUnavailable):
        with journal.guard(other,settings["account_id"],first.job_id,"candidate@example.test",lease_token=first.token):
            test.fail("Cross-tenant job must not dispatch")
    with journal.guard(principal,settings["account_id"],first.job_id,"candidate@example.test",lease_token=first.token):
        pass
    # Fresh guard object represents restart; journal commit must survive.
    restarted=AttemptJournal(worker_repository,key)
    with test.assertRaises(CRMUnavailable):
        with restarted.guard(principal,settings["account_id"],first.job_id,"other@example.test",lease_token=first.token):
            test.fail("Same job must not dispatch again")
    test.assertTrue(leases.finish(principal,first,"needs_review"))
    second=start()
    with test.assertRaises(CRMUnavailable):
        with restarted.guard(principal,settings["account_id"],second.job_id,"Candidate@EXAMPLE.test",lease_token=second.token):
            test.fail("Same candidate must not dispatch under a different job")
    test.assertTrue(leases.finish(principal,second,"failed"))
    third=start()
    with restarted.guard(principal,settings["account_id"],third.job_id,"different@example.test",lease_token=third.token):
        pass
    test.assertTrue(leases.finish(principal,third,"needs_review"))


def verify_sandbox_service(test, *, principal, other, document_repository, worker_repository, storage_root):
    from io import BytesIO
    from types import SimpleNamespace
    from unittest.mock import Mock
    from docx import Document
    from cloud.jobadder_sandbox import SandboxJobAdder, SandboxSession
    from cloud.deploy.workspace_crm_service import SandboxCreateProfile
    from cloud.private_storage import PrivateStorage,DOCX
    from cloud.upload_service import UploadService
    from cloud.documents_jobs import ScopeError

    storage=PrivateStorage(storage_root)
    word=Document()
    word.add_paragraph("Fictional Candidate")
    word.add_paragraph("sandbox-service@example.test")
    word.add_paragraph("Fictional experience only.")
    buffer=BytesIO()
    word.save(buffer)
    raw=buffer.getvalue()
    document=UploadService(document_repository,storage).upload(principal,BytesIO(raw),media_type=DOCX,byte_size=len(raw))
    client=Mock()
    client.request_json.side_effect=[(200,{"items":[],"totalCount":0}),(201,{"candidateId":123})]
    client.request_raw.return_value=SimpleNamespace(status=201)
    def resolve(p):
        if p.tenant_id!=principal.tenant_id:
            raise CRMUnavailable("Unknown sandbox")
        return SandboxSession(p.tenant_id,"fictional-service",1,True,client)
    adapter=SandboxJobAdder(resolve,AttemptJournal(worker_repository,b"j"*32).guard)
    web=SandboxCreateProfile(document_repository,storage,adapter)
    worker=SandboxCreateProfile(worker_repository,storage,adapter)
    review=web.prepare(principal,document)
    test.assertEqual(review["candidate"]["email"],"sandbox-service@example.test")
    test.assertEqual(client.request_json.call_count,0)
    job=web.confirm(principal,document,str(uuid4()),review["confirmation"])
    leases=WorkerLeases(worker_repository)
    lease=leases.claim(principal,cv_only=True,include_profile=True)
    test.assertEqual(lease.job_id,job)
    test.assertTrue(worker.run_claimed(principal,lease,leases))
    test.assertEqual(web.reports(principal,job)["result"],{"outcome":"created","candidate_id":"123","cv_uploaded":True})
    with test.assertRaises(ScopeError):
        web.reports(other,job)
    duplicate=web.confirm(principal,document,str(uuid4()),review["confirmation"])
    lease=leases.claim(principal,cv_only=True,include_profile=True)
    test.assertEqual(lease.job_id,duplicate)
    test.assertFalse(worker.run_claimed(principal,lease,leases))
    test.assertEqual(web.reports(principal,duplicate)["state"],"needs_review")
    test.assertEqual(client.request_json.call_count,2)
    test.assertEqual(client.request_raw.call_count,1)
