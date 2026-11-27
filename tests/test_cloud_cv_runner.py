import unittest
from unittest.mock import Mock,patch
from cloud.cv_runner import run_claimed
from cloud.job_options import Options
from cloud.job_state import State

class TestRunner(unittest.TestCase):
    def test_persisted_options_and_publication(self):
        repo,outputs,workers=Mock(),Mock(),Mock()
        repo.options.return_value=Options("justify",True,False)
        args=dict(principal=Mock(),lease=Mock(),repository=repo,storage=Mock(),workers=workers,ledger=Mock(),policy=Mock(),transport=Mock(),outputs=outputs)
        with patch("cloud.cv_runner.execute_cv_job") as execute:
            self.assertTrue(run_claimed(**args))
            self.assertEqual(execute.call_args.kwargs["alignment"],"justify")
            outputs.publish.assert_called_once_with(args["principal"],args["lease"],execute.return_value)
            outputs.publish.side_effect=OSError("uncertain")
            self.assertFalse(run_claimed(**args))
            workers.finish.assert_called_once_with(args["principal"],args["lease"],State.NEEDS_REVIEW)

    def test_lease_denied_never_processes_or_publishes(self):
        repo,outputs,workers=Mock(),Mock(),Mock()
        workers.heartbeat.return_value=False
        args=dict(principal=Mock(),lease=Mock(),repository=repo,storage=Mock(),workers=workers,ledger=Mock(),policy=Mock(),transport=Mock(),outputs=outputs)
        with patch("cloud.cv_runner.execute_cv_job") as execute:
            self.assertFalse(run_claimed(**args))
            execute.assert_not_called()
            outputs.publish.assert_not_called()
            workers.finish.assert_called_once_with(args["principal"],args["lease"],State.NEEDS_REVIEW)
    def test_lost_final_renewal_prevents_publication(self):
        repo,outputs,workers=Mock(),Mock(),Mock()
        repo.options.return_value=Options()
        workers.heartbeat.side_effect=[True,False]
        args=dict(principal=Mock(),lease=Mock(),repository=repo,storage=Mock(),workers=workers,ledger=Mock(),policy=Mock(),transport=Mock(),outputs=outputs)
        with patch("cloud.cv_runner.execute_cv_job"):
            self.assertFalse(run_claimed(**args))
            outputs.publish.assert_not_called()
