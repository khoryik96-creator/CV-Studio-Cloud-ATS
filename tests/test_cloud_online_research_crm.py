import unittest
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4
from cloud.auth import Principal
from cloud.deploy.workspace_research import ApprovedResearch
from cloud.jobadder_sandbox import SandboxJobAdder,SandboxSession,CRMUnavailable
from cloud.private_storage import DOCX

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.actor=Principal(str(uuid4()),str(uuid4()),"owner","")
        self.other=Principal(str(uuid4()),str(uuid4()),"owner","")
        self.record={"tenant_id":self.actor.tenant_id,"company_name":"Fictional Harbour Labs",
            "sources":[{"id":"overview","title":"Fictional overview","text":"Makes fictional monitoring tools.",
                        "url":"https://research.example.test/overview","retrieved_on":"2026-01-01"}]}
    def test_exact_tenant_company_match(self):
        research=ApprovedResearch([self.record])
        self.assertEqual(research(self.actor," fictional  HARBOUR labs ")[0].id,"overview")
        for actor,name in ((self.other,"Fictional Harbour Labs"),(self.actor,"Harbour"),(self.actor,"https://example.test")):
            with self.assertRaises(ValueError):
                research(actor,name)
    def test_duplicate_and_missing_citations_denied(self):
        with self.assertRaises(ValueError):
            ApprovedResearch([self.record,self.record])
        self.record["sources"][0]["url"]="http://example.test"
        with self.assertRaises(ValueError):
            ApprovedResearch([self.record])

class SandboxCRMTests(unittest.TestCase):
    def setUp(self):
        self.actor=Principal(str(uuid4()),str(uuid4()),"owner","")
        self.client=Mock()
        self.session=SandboxSession(self.actor.tenant_id,"sandbox-account",1,True,self.client)
        self.resolve=Mock(return_value=self.session)
        self.attempted=set()
        @contextmanager
        def guard(p,account,job,email,*,lease_token):
            key=(p.tenant_id,account,job)
            if key in self.attempted:
                raise CRMUnavailable("Attempt already recorded")
            self.attempted.add(key)
            yield
        self.adapter=SandboxJobAdder(self.resolve,guard)
        self.settings=self.adapter.settings(self.actor)
        self.job=str(uuid4())
        self.lease_token=str(uuid4())
        self.candidate={"name":"Fictional Person","email":"fictional@example.test"}

    def submit(self,**kw):
        return self.adapter.create_with_cv(self.actor,self.job,self.settings,
            self.candidate,kw.get("raw",b"fictional document"),kw.get("mime",DOCX),lease_token=self.lease_token)

    def test_create_then_attach_once_without_retries(self):
        self.client.request_json.side_effect=[(200,{"items":[],"totalCount":0}),(201,{"candidateId":123})]
        self.client.request_raw.return_value=SimpleNamespace(status=201)
        self.assertEqual(self.submit(),{"outcome":"created","candidate_id":"123","cv_uploaded":True})
        self.assertEqual(self.client.request_json.call_count,2)
        args,kw=self.client.request_raw.call_args
        self.assertEqual(args,("candidates/123/attachments/Resume",))
        self.assertIn(b'name="fileData"',kw["body"])
        for call in self.client.request_json.call_args_list+self.client.request_raw.call_args_list:
            self.assertFalse(call.kwargs["refresh_on_401"])
            self.assertFalse(call.kwargs["safe_to_retry"])
            self.assertEqual(call.kwargs["retries"],0)
        with self.assertRaises(CRMUnavailable):
            self.submit()
        self.assertEqual(self.client.request_raw.call_count,1)

    def test_duplicate_never_writes(self):
        self.client.request_json.return_value=(200,{"items":[{"candidateId":55}],"totalCount":1})
        self.assertEqual(self.submit()["outcome"],"duplicate")
        self.assertEqual(self.client.request_json.call_count,1)
        self.client.request_raw.assert_not_called()

    def test_unknown_search_fails_closed(self):
        self.client.request_json.return_value=(200,{"items":[]})
        with self.assertRaises(CRMUnavailable):
            self.submit()
        self.assertEqual(self.client.request_json.call_count,1)
        self.client.request_raw.assert_not_called()

    def test_account_change_and_non_sandbox_refused(self):
        for session in (replace(self.session,sandbox=False),replace(self.session,revision=2),
                        replace(self.session,tenant_id=str(uuid4()))):
            self.resolve.return_value=session
            with self.assertRaises(CRMUnavailable):
                self.submit()
        self.client.request_json.assert_not_called()

    def test_upload_failure_not_replayed_or_reported_success(self):
        self.client.request_json.side_effect=[(200,{"items":[],"totalCount":0}),(201,{"candidateId":123})]
        self.client.request_raw.side_effect=TimeoutError("private remote detail")
        with self.assertRaisesRegex(CRMUnavailable,"requires review"):
            self.submit()
        self.assertIsNone(self.adapter.reconcile(self.actor,self.job,self.settings))
        with self.assertRaises(CRMUnavailable):
            self.submit()
        self.assertEqual(self.client.request_raw.call_count,1)

if __name__=="__main__":
    unittest.main()
