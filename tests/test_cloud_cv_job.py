import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from cloud.cv_job import execute_cv_job,JobExecutionError
from cloud.worker_leases import Lease
from cloud.auth import Principal

class TestJobAdapter(unittest.TestCase):
    def test_mismatch_rejected_before_read_or_ai(self):
        ids=[str(uuid4()) for _ in range(5)]
        p=Principal(ids[0],ids[1],"recruiter","synthetic")
        lease=Lease(ids[2],ids[3],"cv_formatting",ids[4])
        repo=Mock()
        repo.job.return_value=(lease.job_id,"cv_blinding","running",lease.document_id)
        storage,workers,ledger,transport=Mock(),Mock(),Mock(),Mock()
        workers.heartbeat.return_value=True
        with self.assertRaisesRegex(JobExecutionError,"metadata_mismatch"):
            execute_cv_job(principal=p,lease=lease,repository=repo,storage=storage,workers=workers,ledger=ledger,policy=None,transport=transport)
        repo.document.assert_not_called()
        storage.read_verified.assert_not_called()
        transport.assert_not_called()
    def test_expired_lease_rejected(self):
        workers=Mock()
        workers.heartbeat.return_value=False
        repo=Mock()
        lease=Lease(str(uuid4()),str(uuid4()),"cv_formatting",str(uuid4()))
        with self.assertRaisesRegex(JobExecutionError,"lease_lost"):
            execute_cv_job(principal=None,lease=lease,repository=repo,storage=Mock(),workers=workers,ledger=Mock(),policy=None,transport=Mock())
        repo.job.assert_not_called()
