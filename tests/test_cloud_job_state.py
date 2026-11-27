import unittest
from cloud.job_state import State, transition, expired_lease
from cloud.documents_jobs import DocumentJobs, ScopeError, MAX_BYTES
from cloud.auth import Principal

class TestJobState(unittest.TestCase):
    def test_no_replay_after_lease_expiry(self):
        self.assertEqual(expired_lease(State.RUNNING),State.NEEDS_REVIEW)
        for state in (State.RUNNING,State.NEEDS_REVIEW,State.SUCCEEDED,State.FAILED):
            with self.assertRaises(ValueError):
                transition(state,State.QUEUED)
    def test_completion(self):
        self.assertEqual(transition(State.QUEUED,State.RUNNING),State.RUNNING)
        self.assertEqual(transition(State.RUNNING,State.SUCCEEDED),State.SUCCEEDED)
    def test_invalid_scope_never_connects(self):
        def forbidden():
            raise AssertionError("Must reject before DB access")
        repo=DocumentJobs(forbidden)
        with self.assertRaises(ScopeError):
            repo.document(None,"00000000-0000-0000-0000-000000000000")
        with self.assertRaises(ValueError):
            repo.register_document(None,media_type="text/plain",byte_size=MAX_BYTES+1,sha256="a"*64)
        with self.assertRaises(ValueError):
            repo.enqueue(None,document_id="bad",module="jobadder",idempotency_key="bad")
