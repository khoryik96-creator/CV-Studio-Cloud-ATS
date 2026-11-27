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

def compose_synthetic(*,connect,storage_root,principals,public_origin,fixture_source,fixture_answer,concurrency=1,enable_batch=False):
    """Run one known fictional fixture through real storage/queue/renderer.

    A worker may accept only the exact supplied fixture text after the engine's
    source preparation. Other inputs are refused without any external call.
    The injected connection must target an isolated disposable test database.
    """
    from cloud.cv_engine import prepare_source,answer_json
    if not isinstance(fixture_source,str) or not isinstance(fixture_answer,str):
        raise ValueError("Fictional fixture strings required")
    if not public_origin.endswith(".test"):
        raise ValueError("Reserved .test staging host required")
    expected=prepare_source(fixture_source)
    answer_json(fixture_answer)
    repo=DocumentJobs(connect)
    storage=PrivateStorage(storage_root)
    uploads=UploadService(repo,storage)
    outputs=JobOutputs(repo,storage)
    workers=WorkerLeases(repo)
    ledger=AIBudget(repo)
    # Synthetic metering values, deliberately not live provider prices.
    policy=ModelPolicy("deepseek","synthetic-model",1,1,200000,32000)
    def resolve(principal):
        def fake(provider,model,system,prompt,limit):
            if (provider,model)!=("deepseek","synthetic-model") or prompt!=expected:
                raise ValueError("synthetic_fixture_only")
            return Completion(fixture_answer,100,100)
        return policy,fake
    app=create_app(auth_store=PostgresAuthStore(connect),public_origin=public_origin,cv_services=(uploads,repo,outputs))
    register_existing_ui(app,enable_batch=enable_batch)
    worker=WorkerRuntime(principals=principals,repository=repo,storage=storage,workers=workers,
        ledger=ledger,outputs=outputs,resolve_provider=resolve,concurrency=concurrency,enable_ocr=False)
    return SyntheticEnvironment(app,worker)
