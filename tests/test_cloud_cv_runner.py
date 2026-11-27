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
