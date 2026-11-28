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
