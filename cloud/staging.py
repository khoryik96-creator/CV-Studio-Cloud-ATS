"""Explicit synthetic-only composition; not a public production entry point.

Caller provides fresh database transactions and a private disposable volume.
No live provider transport, migrations, discovery, HTTP worker trigger, or
automatic account provisioning. Do not connect to production databases.
"""
from dataclasses import dataclass
import json
from cloud.auth_postgres import PostgresAuthStore
from cloud.documents_jobs import DocumentJobs
from cloud.private_storage import PrivateStorage
from cloud.upload_service import UploadService
from cloud.job_outputs import JobOutputs
from cloud.worker_leases import WorkerLeases
from cloud.ai_budget import AIBudget
from cloud.ai_dispatch import ModelPolicy,Completion
from cloud.worker_runtime import WorkerRuntime
from cloud.app import create_app
from cloud.frontend.shell import register_existing_ui

@dataclass(frozen=True,repr=False)
class SyntheticEnvironment:
    app: object
    worker: WorkerRuntime

def compose_synthetic(*,connect,storage_root,principals,public_origin,fixture_source,fixture_answer,fixture_blind_answer=None,fixture_scoring_jd=None,fixture_report_sources=None,concurrency=1,enable_batch=False,strict_upload=False):
    """Run one known fictional fixture through real storage/queue/renderer.

    A worker may accept only the exact supplied fixture text after the engine's
    source preparation. Other inputs are refused without any external call.
    The injected connection must target an isolated disposable test database.
    """
    from cloud.cv_engine import prepare_source,answer_json,blind_prompt,parse_prompt
    if not isinstance(fixture_source,str) or not isinstance(fixture_answer,str):
        raise ValueError("Fictional fixture strings required")
    if not public_origin.endswith(".test"):
        raise ValueError("Reserved .test staging host required")
    expected=prepare_source(fixture_source)
    answer_json(fixture_answer)
    parse_systems = (parse_prompt(), parse_prompt(correct_language=True))
    blind_systems = ()
    if fixture_blind_answer is not None:
        answer_json(fixture_blind_answer)
        blind_systems = (blind_prompt(), blind_prompt(neutral_gender=True))
    scoring_enabled = fixture_scoring_jd is not None
    sources = [fixture_source]
    if scoring_enabled:
        from cloud.file_extract import extract
        from cloud.scoring_contract import Criterion, prepare
        sources.append(fixture_scoring_jd)
        scoring_cv, scoring_jd = (extract(value.encode("utf-8"), "text/plain").text for value in sources)
        scoring_evidence = {
            "Automate recovery checks with Ansible.": "Automated recovery checks with Ansible.",
            "Manage enterprise Kubernetes clusters.": "",
        }
        scoring_system, _ = prepare(scoring_cv, scoring_jd, [Criterion("fixture", next(iter(scoring_evidence)), True)])
    research = None
    report_completion = None
    if fixture_report_sources is not None:
        from cloud.file_extract import extract
        from cloud.deploy import report_fixtures
        jd_source, company_name = fixture_report_sources
        sources.extend((jd_source, company_name))
        research = report_fixtures.research
        report_completion = report_fixtures.completion(extract(jd_source.encode("utf-8"), "text/plain").text)
    repo=DocumentJobs(connect)
    storage=PrivateStorage(storage_root)
    uploads=UploadService(repo,storage)
    if strict_upload:
        from cloud.deploy.fixture_upload import FixtureUpload
        uploads=FixtureUpload(uploads,*sources)
    outputs=JobOutputs(repo,storage)
    workers=WorkerLeases(repo)
    ledger=AIBudget(repo)
    # Synthetic metering values, deliberately not live provider prices.
    policy=ModelPolicy("deepseek","synthetic-model",1,1,200000,32000)
    def resolve(principal):
        def fake(provider,model,system,prompt,limit):
            if (provider, model) == ("deepseek", "synthetic-model"):
                if system in parse_systems and prompt == expected:
                    return Completion(fixture_answer, 100, 100)
                if system in blind_systems and prompt.startswith("Anonymise this parsed CV JSON:\n\n"):
                    return Completion(fixture_blind_answer, 100, 100)
                if scoring_enabled and system == scoring_system:
                    data = json.loads(prompt)
                    if data["cv"].strip() == scoring_cv.strip() and data["jd"].strip() == scoring_jd.strip():
                        assessments = []
                        for criterion in data["criteria"]:
                            quote = scoring_evidence[criterion["requirement"]]
                            status = "evidenced" if quote else "not_evidenced"
                            note = ("The CV describes an Ansible automation project." if quote
                                    else "The CV has no Kubernetes cluster management evidence.")
                            assessments.append(dict(id=criterion["id"], status=status, quote=quote, note=note))
                        return Completion(json.dumps({"assessments": assessments}), 100, 100)
                if report_completion is not None:
                    return report_completion(system, prompt)
            raise ValueError("synthetic_fixture_only")
        return policy,fake
    app=create_app(auth_store=PostgresAuthStore(connect),public_origin=public_origin,cv_services=(uploads,repo,outputs),enable_scoring=scoring_enabled,enable_reports=research is not None)
    register_existing_ui(app,enable_batch=enable_batch)
    worker=WorkerRuntime(principals=principals,repository=repo,storage=storage,workers=workers,
        ledger=ledger,outputs=outputs,resolve_provider=resolve,concurrency=concurrency,enable_ocr=False,enable_scoring=scoring_enabled,research=research)
    return SyntheticEnvironment(app,worker)
