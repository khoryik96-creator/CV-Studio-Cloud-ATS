"""Full restricted online worker acceptance, fictional files and no network."""
import io
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

def verify_worker_acceptance(test, *, principal, other, storage_root, document_connect,
                             worker_connect, provider_connect, cipher, catalogue, policy):
    from cloud.ai_dispatch import Completion
    from cloud.cv_engine import prepare_source,parse_prompt,blind_prompt
    from cloud.deploy.online_workspace import assemble_worker
    from cloud.deploy.workspace_repository import OnlineDocumentJobs
    from cloud.file_extract import extract
    from cloud.job_outputs import JobOutputs
    from cloud.private_storage import PrivateStorage
    from cloud.scoring_contract import Criterion,prepare
    from cloud.scoring_jobs import reports
    from cloud.upload_service import UploadService
    fixtures=Path(__file__).resolve().parent/"fixtures"
    source=(fixtures/"cloud_cv_source.txt").read_text(encoding="utf-8")
    jd=(fixtures/"cloud_cv_scoring_jd.txt").read_text(encoding="utf-8")
    parsed=(fixtures/"cloud_cv_parse.json").read_text(encoding="utf-8")
    blinded=(fixtures/"cloud_cv_blind.json").read_text(encoding="utf-8")
    rubric=(Criterion("ansible","Automate recovery checks with Ansible.",True),)
    cv_text=extract(source.encode(),"text/plain").text
    jd_text=extract(jd.encode(),"text/plain").text
    expected=prepare_source(source)
    scoring_system,scoring_user=prepare(cv_text,jd_text,rubric)
    calls=[]
    def factory(secret):
        test.assertEqual(secret,"fictional-key")
        def fake(provider,model,system,prompt,limit):
            test.assertEqual((provider,model),(policy.provider,policy.model))
            if system==parse_prompt() and prompt==expected:
                calls.append("parse")
                return Completion(parsed,100,100)
            if system==blind_prompt() and prompt.startswith("Anonymise this parsed CV JSON:\n\n"):
                calls.append("blind")
                return Completion(blinded,100,100)
            if system==scoring_system and prompt==scoring_user:
                calls.append("assess")
                return Completion(json.dumps({"assessments":[{"id":"ansible","status":"evidenced",
                    "quote":"Automated recovery checks with Ansible.","note":"Explicit automation evidence."}]}),100,100)
            raise AssertionError("Unexpected fixture request; no external transport")
        return fake
    repository=OnlineDocumentJobs(document_connect)
    storage=PrivateStorage(storage_root)
    upload=UploadService(repository,storage)
    def put(value):
        raw=value.encode("utf-8")
        return upload.upload(principal,io.BytesIO(raw),media_type="text/plain",byte_size=len(raw))
    cv_id,jd_id=put(source),put(jd)
    runtime=assemble_worker(worker_connect=worker_connect,provider_connect=provider_connect,
        storage_root=storage_root,cipher=cipher,catalogue=catalogue,principals=(principal,),
        concurrency=1,transport_factory=factory)
    outputs=JobOutputs(repository,storage)
    for module in ("cv_formatting","cv_blinding","cv_scoring"):
        options={"scoring":(jd_id,rubric)} if module=="cv_scoring" else {}
        job=repository.enqueue(principal,document_id=cv_id,module=module,
            idempotency_key=str(uuid4()),**options)
        test.assertEqual(runtime.tick(),("completed",),module)
        if module=="cv_scoring":
            result=reports(repository,principal,job)
            test.assertEqual(result["state"],"succeeded")
            test.assertTrue(result["assessment"]["human_review_required"])
            test.assertEqual(result["assessment"]["assessments"][0]["status"],"evidenced")
            test.assertIsNone(reports(repository,other,job))
        else:
            output=outputs.download(principal,job)
            test.assertIsNotNone(output,module)
            test.assertIsNone(outputs.download(other,job))
            if module=="cv_blinding":
                test.assertTrue(output.requires_review)
            with ZipFile(io.BytesIO(output.document)) as package:
                test.assertIn("word/document.xml",package.namelist())
    test.assertEqual(calls,["parse","parse","blind","assess"])
    test.assertEqual(runtime.tick(),("idle",))
