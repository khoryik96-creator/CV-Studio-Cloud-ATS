import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from cloud.auth import Principal
from cloud.worker_runtime import WorkerRuntime

class TestRuntime(unittest.TestCase):
    def make(self,principals,**extra):
        self.workers=Mock()
        self.resolve=Mock(return_value=(Mock(),Mock()))
        args=dict(principals=principals,repository=Mock(),storage=Mock(),workers=self.workers,ledger=Mock(),outputs=Mock(),resolve_provider=self.resolve)
        args.update(extra)
        return WorkerRuntime(**args)
    def test_bounded_round_and_rotation(self):
        t,u=str(uuid4()),str(uuid4())
        a,b,c=[Principal(t if i<2 else u,str(uuid4()),"recruiter","") for i in range(3)]
        runtime=self.make([a,b,c],concurrency=2)
        with patch("cloud.worker_runtime.run_claimed",return_value=True) as run:
            self.assertEqual(runtime.tick(),("completed","completed"))
            self.assertEqual({x.kwargs["principal"] for x in run.call_args_list},{a,c})
            self.assertTrue(all(x.kwargs=={"cv_only":True} for x in self.workers.claim.call_args_list))
            run.reset_mock()
            runtime.tick()
            self.assertEqual({x.kwargs["principal"] for x in run.call_args_list},{a,b})
    def test_provider_unavailable_never_claims(self):
        p=Principal(str(uuid4()),str(uuid4()),"recruiter","")
        runtime=self.make([p])
        self.resolve.side_effect=ValueError("missing configuration")
        self.assertEqual(runtime.tick(),("unavailable",))
        self.workers.claim.assert_not_called()
    def test_idle_and_duplicate_owners(self):
        p=Principal(str(uuid4()),str(uuid4()),"recruiter","")
        runtime=self.make([p])
        self.workers.claim.return_value=None
        self.assertEqual(runtime.tick(),("idle",))
        with self.assertRaises(ValueError):
            self.make([p,p])
        with self.assertRaises(ValueError):
            self.make([p],concurrency=8)
