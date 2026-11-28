from datetime import datetime, timezone
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

from cloud.deploy.workspace_heartbeat import Heartbeat,healthy,MAX_ROUND
from cloud.deploy.workspace_config import load_policy,require_live_worker_approval,concurrency,live_worker_cutoff
from cloud.frontend.shell import render_shell

class WorkspaceRuntimeTests(unittest.TestCase):
    def test_heartbeat_expiry_and_round_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"heartbeat.json"
            clock=Mock(return_value=100.0)
            exit_process=Mock()
            heartbeat=Heartbeat(path,clock=clock,exit_process=exit_process)
            self.assertFalse(healthy(path,clock=clock))
            heartbeat.set("running")
            self.assertTrue(healthy(path,clock=clock))
            clock.return_value=121.0
            self.assertFalse(healthy(path,clock=clock))
            heartbeat._write()
            self.assertTrue(healthy(path,clock=clock))
            clock.return_value=100+MAX_ROUND+1
            heartbeat._write()
            exit_process.assert_called_once_with(1)
            self.assertFalse(healthy(path,clock=clock))

    def test_live_worker_is_explicitly_disabled_by_default(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(RuntimeError):
                require_live_worker_approval()
            self.assertEqual(concurrency(),2)
        with patch.dict(os.environ,{"CVCLOUD_LIVE_AI":"operator-approved","CVCLOUD_WORKER_CONCURRENCY":"4"}):
            require_live_worker_approval()
            self.assertEqual(concurrency(),4)
        with patch.dict(os.environ,{"CVCLOUD_WORKER_CONCURRENCY":"5"}):
            with self.assertRaises(ValueError):
                concurrency()

    def test_live_worker_requires_fixed_cutoff(self):
        with patch.dict(os.environ, {"CVCLOUD_LIVE_AI": "operator-approved"}, clear=True):
            with self.assertRaises(ValueError):
                live_worker_cutoff()
            os.environ["CVCLOUD_WORKER_ADMIT_AFTER"] = "2026-11-28T16:00:00Z"
            self.assertEqual(live_worker_cutoff(), datetime(2026, 11, 28, 16, tzinfo=timezone.utc))

    def test_explicit_catalogue_and_keyring(self):
        with tempfile.TemporaryDirectory() as directory:
            keyring=Path(directory)/"keys.json"
            models=Path(directory)/"models.json"
            keyring.write_text(json.dumps({"active_version":"v1","keys":{"v1":"11"*32}}))
            models.write_text(json.dumps([{"provider":"deepseek","model":"fictional-model",
                "input_rate":100,"output_rate":200,"max_input_tokens":4096,"max_output_tokens":1024}]))
            with patch.dict(os.environ,{"CVCLOUD_KEYRING_FILE":str(keyring),"CVCLOUD_MODEL_CATALOGUE_FILE":str(models)}):
                _,catalogue=load_policy()
                self.assertEqual(catalogue.get("deepseek","fictional-model").input_rate,100)
                models.write_text("[]")
                with self.assertRaises(ValueError):
                    load_policy()

    def test_blind_jd_candidate_separate_from_research(self):
        candidate=render_shell(online_candidate=True,enable_blind_jd=True)
        self.assertIn(b'id="viewJDAnon"',candidate)
        self.assertNotIn(b'id="viewCompany"',candidate)

    def test_online_candidate_preserves_original_tabs_as_locked(self):
        from lxml import html
        from cloud.frontend.shell import ROOT
        original=html.parse(str(ROOT/"index.html")).getroot()
        page=html.fromstring(render_shell(online_candidate=True,enable_batch=True,enable_scoring=True,enable_blind_jd=True))
        ids=lambda doc:[n.get("id") for n in doc.xpath(".//*[@id='pageTabs']/button") if (n.get("id") or "").startswith("tab")]
        self.assertEqual(ids(page),ids(original))
        for key in ("Summary","JACreate","Company","TheOwl","JAUpload","OneNote"):
            tab=page.xpath(".//*[@id=$key]",key="tab"+key)[0]
            self.assertEqual(tab.get("disabled"),"disabled")
            self.assertIn("Locked",tab.text_content())
            self.assertFalse(page.xpath(".//*[@id=$key]",key="view"+key))

    def test_candidate_ui_does_not_enable_unverified_modules(self):
        self.assertIn(b"Cloud staging",render_shell())
        candidate=render_shell(online_candidate=True,enable_scoring=True,enable_batch=True)
        self.assertIn(b'data-resume-session="true"',candidate)
        self.assertIn(b"Online workspace candidate",candidate)
        self.assertNotIn(b"Cloud staging",candidate)
        with self.assertRaises(ValueError):
            render_shell(online_candidate=True,enable_profile=True)
        research=render_shell(online_candidate=True,enable_reports=True)
        self.assertIn(b"operator-approved research excerpts",research)
        self.assertNotIn(b"fictional research sources",research)

if __name__=="__main__":
    unittest.main()
