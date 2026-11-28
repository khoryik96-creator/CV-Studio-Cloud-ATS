"""Explicit synthetic-only composition; not a public production entry point.

Caller provides fresh database transactions and a private disposable volume.
No live provider transport, migrations, discovery, HTTP worker trigger, or
automatic account provisioning. Do not connect to production databases.
"""
from dataclasses import dataclass
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

def compose_synthetic(*,connect,storage_root,principals,public_origin,fixture_source,fixture_answer,fixture_blind_answer=None,concurrency=1,enable_batch=False,strict_upload=False):
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
    repo=DocumentJobs(connect)
    storage=PrivateStorage(storage_root)
    uploads=UploadService(repo,storage)
    if strict_upload:
        from cloud.deploy.fixture_upload import FixtureUpload
        uploads=FixtureUpload(uploads,fixture_source)
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
            raise ValueError("synthetic_fixture_only")
        return policy,fake
    app=create_app(auth_store=PostgresAuthStore(connect),public_origin=public_origin,cv_services=(uploads,repo,outputs))
    register_existing_ui(app,enable_batch=enable_batch)
    worker=WorkerRuntime(principals=principals,repository=repo,storage=storage,workers=workers,
        ledger=ledger,outputs=outputs,resolve_provider=resolve,concurrency=concurrency,enable_ocr=False)
    return SyntheticEnvironment(app,worker)
