"""Unit contract for function-only online account/usage adapters."""
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from cloud.account_admin import AccountAdminError
from cloud.documents_jobs import ScopeError
from cloud.deploy.online_admin_services import OnlineAccountAdmin,OnlineAIUsage

class Repository:
    def __init__(self):
        self.conn=Mock()
    @contextmanager
    def scoped(self,principal):
        yield self.conn,principal.tenant_id,principal.user_id

class OnlineAdminServicesTests(unittest.TestCase):
    def setUp(self):
        self.repo=Repository()
        self.actor=SimpleNamespace(tenant_id=str(uuid4()),user_id=str(uuid4()))
        self.target=str(uuid4())
        self.row=(self.target,"fictional@example.test","recruiter",True,2)
        self.admin=OnlineAccountAdmin(self.repo)

    def test_list_uses_only_restricted_function(self):
        self.repo.conn.execute.return_value.fetchall.return_value=[self.row]
        self.assertEqual(self.admin.list_accounts(self.actor)[0].user_id,self.target)
        self.repo.conn.execute.assert_called_once_with("SELECT * FROM cvcloud.admin_list_accounts()")

    def test_no_password_or_owner_actions(self):
        for action,value in (("password_reset","never"),("role_change","owner"),("suspend",True)):
            with self.assertRaises(AccountAdminError):
                self.admin.change(self.actor,user_id=self.target,expected_revision=1,action=action,value=value)
        self.repo.conn.execute.assert_not_called()

    def test_valid_action_calls_function(self):
        self.repo.conn.execute.return_value.fetchone.return_value=self.row
        status=self.admin.change(self.actor,user_id=self.target,expected_revision=1,action="revoke_sessions")
        self.assertEqual(status.revision,2)
        statement,args=self.repo.conn.execute.call_args.args
        self.assertIn("cvcloud.admin_change_account",statement)
        self.assertEqual(args[:4],(self.target,1,"revoke_sessions",None))

    def test_usage_arithmetic_and_missing_budget(self):
        service=OnlineAIUsage(self.repo)
        self.repo.conn.execute.return_value.fetchone.return_value=None
        self.assertEqual(service.snapshot(self.actor),{"configured":False})
        self.repo.conn.execute.return_value.fetchone.return_value=(100,60,50)
        self.assertEqual(service.snapshot(self.actor)["over_limit_microusd"],"10")
        self.assertEqual(service.snapshot(self.actor)["remaining_microusd"],"0")

    def test_only_known_errors_mapped(self):
        class DBError(Exception):
            sqlstate="P0001"
            diag=SimpleNamespace(message_primary="account_admin_denied")
        self.repo.conn.execute.side_effect=DBError("do not expose internal details")
        with self.assertRaisesRegex(AccountAdminError,"^account_admin_denied$"):
            self.admin.list_accounts(self.actor)
        with self.assertRaises(ScopeError):
            OnlineAIUsage(self.repo).snapshot(self.actor)

if __name__=="__main__":
    unittest.main()
