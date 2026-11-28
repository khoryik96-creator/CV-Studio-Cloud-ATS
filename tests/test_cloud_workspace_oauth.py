"""Hermetic Linux vault and sandbox lifecycle tests."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit,parse_qs
from uuid import uuid4
from cloud.auth import Principal
from cloud.deploy.workspace_crm_binding import ApprovedSandbox,SandboxBindings
from cloud.deploy.workspace_oauth_vault import OAuthVault,VaultError
from cloud.deploy.workspace_oauth_lifecycle import SandboxOAuth
from cloud.jobadder_sandbox import CRMUnavailable

@unittest.skipUnless(os.name=="posix","POSIX private vault required")
class OAuthLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.actor=Principal(str(uuid4()),str(uuid4()),"owner","fictional-session")
        self.other=Principal(self.actor.tenant_id,str(uuid4()),"owner","other-session")
        self.clock=Mock(return_value=1000)
        self.keys={"v1":b"a"*32}
        self.vault=OAuthVault(self.path,keys=self.keys,active_version="v1")
        self.approved=ApprovedSandbox(self.actor.tenant_id,"sandbox",123,"https://api.jobadder.com/v2",1)
        self.bindings=SandboxBindings([self.approved],clock=self.clock,client_factory=Mock())
        self.response={"instance":"sandbox","account":123,"api":self.approved.api,"token_type":"Bearer",
            "expires_in":3600,"access_token":"fictional-access-token","refresh_token":"fictional-refresh-token"}
        self.exchange=Mock(return_value=self.response)
        self.service=self.build(self.vault)
    def build(self,vault):
        return SandboxOAuth(vault,self.bindings,self.exchange,client_id="fictional-client",
            client_secret="fictional-secret",redirect_uri="https://cvstudio.hyplug.co/api/admin/jobadder/callback",
            scope="offline_access",clock=self.clock)
    def state(self):
        return parse_qs(urlsplit(self.service.begin(self.actor)).query)["state"][0]
    def login(self):
        return self.service.complete(self.actor,state=self.state(),code="fictional-code")
    def test_single_use_owner_session_and_restart(self):
        state=self.state()
        self.assertNotIn(state.encode(),(self.path/(self.actor.tenant_id+".json")).read_bytes())
        for actor,attempt in ((self.other,state),(self.actor,"wrong-state")):
            with self.assertRaises(CRMUnavailable):
                self.service.complete(actor,state=attempt,code="fictional-code")
        self.exchange.assert_not_called()
        restarted=self.build(OAuthVault(self.path,keys=self.keys,active_version="v1"))
        self.assertEqual(restarted.complete(self.actor,state=state,code="fictional-code").revision,1)
        with self.assertRaises(CRMUnavailable):
            restarted.complete(self.actor,state=state,code="fictional-code")
        self.exchange.assert_called_once()
        self.assertNotIn(b"fictional-refresh-token",(self.path/(self.actor.tenant_id+".json")).read_bytes())
    def test_rotating_refresh_preserves_revision_and_disconnect_increments(self):
        self.login()
        self.clock.return_value=4500
        self.exchange.return_value=dict(self.response,access_token="new-fictional-access-token",refresh_token="new-fictional-refresh-token")
        self.assertEqual(self.service.resolve(self.actor).revision,1)
        self.assertEqual(self.exchange.call_args.args[0]["grant_type"],"refresh_token")
        self.assertEqual(self.exchange.call_args.args[0]["refresh_token"],"fictional-refresh-token")
        self.service.disconnect(self.actor)
        self.assertEqual(self.service.status(self.actor),{"state":"disconnected","revision":2})
        with self.assertRaises(CRMUnavailable):
            self.service.resolve(self.actor)
    def test_uncertain_refresh_never_replays(self):
        self.login()
        self.clock.return_value=4500
        self.exchange.side_effect=TimeoutError("secret remote details")
        for _ in range(2):
            with self.assertRaises(CRMUnavailable):
                self.service.resolve(self.actor)
        self.assertEqual(self.exchange.call_count,2)
        self.assertEqual(self.service.status(self.actor)["state"],"reconnect_required")
    def test_mismatch_and_expiry(self):
        state=self.state()
        self.clock.return_value=1300
        with self.assertRaises(CRMUnavailable):
            self.service.complete(self.actor,state=state,code="fictional-code")
        self.exchange.assert_not_called()
        self.exchange.return_value=dict(self.response,account=999)
        with self.assertRaises(CRMUnavailable):
            self.login()
        self.assertEqual(self.service.status(self.actor)["state"],"reconnect_required")
    def test_tampering_and_tenant_swap(self):
        self.login()
        path=self.path/(self.actor.tenant_id+".json")
        foreign=str(uuid4())
        target=self.path/(foreign+".json")
        target.write_bytes(path.read_bytes())
        target.chmod(0o600)
        with self.assertRaises(VaultError):
            with self.vault.locked(foreign):
                pass
        raw=bytearray(path.read_bytes())
        raw[-8]^=1
        path.write_bytes(raw)
        with self.assertRaises(VaultError):
            self.service.status(self.actor)
    def test_process_lock_and_crash_marker(self):
        with self.vault.locked(self.actor.tenant_id) as (_,save):
            with self.assertRaises(VaultError):
                self.service.status(self.actor)
            save({"revision":1,"state":"refreshing"})
        with self.assertRaises(CRMUnavailable):
            self.service.resolve(self.actor)
        self.exchange.assert_not_called()

if __name__=="__main__":
    unittest.main()
