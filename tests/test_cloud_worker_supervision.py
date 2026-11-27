import unittest
from threading import Event
from cloud.worker_supervision import LeaseSupervisor,LeaseLost

class TestSupervisor(unittest.TestCase):
    def test_initial_lease_denial(self):
        with self.assertRaises(LeaseLost):
            with LeaseSupervisor(lambda:False):
                self.fail("work must not begin")
    def test_deadline_is_checked_before_work(self):
        now=[0]
        with self.assertRaises(LeaseLost):
            with LeaseSupervisor(lambda:True,deadline=60,clock=lambda:now[0]) as s:
                s.check()
                now[0]=61
                s.check()
    def test_background_renewal_and_loss(self):
        attempts=[]
        signal=Event()
        def renew():
            attempts.append(1)
            if len(attempts)>1:
                signal.set()
                return False
            return True
        with self.assertRaises(LeaseLost):
            with LeaseSupervisor(renew,interval=.01,deadline=2):
                self.assertTrue(signal.wait(1))
        self.assertEqual(len(attempts),2)
    def test_no_reuse(self):
        s=LeaseSupervisor(lambda:True)
        with s:
            s.check()
        with self.assertRaises(RuntimeError):
            with s:
                pass
