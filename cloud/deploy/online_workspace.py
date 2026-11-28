"""Internal assembly of existing cloud CV components.

This is not a public deployment entry point. The caller must supply dedicated,
verified database roles and operator-approved model policy. Do not start a
listener or worker from this module. No synthetic providers are selected.
"""
from cloud.ai_budget import AIBudget
from cloud.deploy.online_admin_services import OnlineAccountAdmin, OnlineAIUsage
from cloud.deploy.workspace_admin_install import verify_admin_role
from cloud.app import create_app
from cloud.deploy.online_auth import DedicatedAuthStore, TrustedProxyOnly, verify_database
from cloud.deploy.workspace_repository import OnlineDocumentJobs
from cloud.frontend.shell import register_existing_ui
from cloud.job_outputs import JobOutputs
from cloud.private_storage import PrivateStorage
from cloud.provider_config import ProviderConfig
from cloud.upload_service import UploadService
from cloud.worker_leases import WorkerLeases
from cloud.worker_runtime import WorkerRuntime
from cloud.deploy.workspace_roles import verify_service_role


def assemble_workspace(*, config, auth_connect, document_connect,
                       provider_connect, storage_root,
                       cipher, catalogue, admin_connect=None, enable_blind_jd=False, enable_company_profile=False):
    """Build internal web candidate for formatting, blinding and scoring.

    Connections are transaction factories supplied by a future verified
    deployment root. In particular, the authentication-only role must not be
    used for document or administration operations. Provider configuration
    receives its own write-only credential connection factory. Administration
    is optional and requires verified function-only access. JobAdder and research
    remain disabled.
    """
    factories = (auth_connect, document_connect, provider_connect) + ((admin_connect,) if admin_connect is not None else ())
    if not all(callable(f) for f in factories) or len({id(f) for f in factories}) != len(factories):
        raise ValueError("Separate database connection factories required")
    verify_database(auth_connect)
    for service, connect in (("document", document_connect), ("provider", provider_connect)):
        verify_service_role(connect, service)
    admin = None
    if admin_connect is not None:
        verify_admin_role(admin_connect)
        admin = OnlineDocumentJobs(admin_connect)
    documents = OnlineDocumentJobs(document_connect)
    provider = ProviderConfig(OnlineDocumentJobs(provider_connect), cipher, catalogue)
    storage = PrivateStorage(storage_root)
    app = create_app(
        auth_store=DedicatedAuthStore(auth_connect),
        public_origin=config.origin,
        cv_services=(UploadService(documents, storage), documents,
                     JobOutputs(documents, storage)),
        provider_admin=provider,
        account_admin=OnlineAccountAdmin(admin) if admin is not None else None,
        ai_usage=OnlineAIUsage(admin) if admin is not None else None,
        enable_scoring=True,
        enable_blind_jd=enable_blind_jd,
        enable_reports=enable_company_profile,
    )
    register_existing_ui(app, enable_batch=True, online_candidate=True)
    app.wsgi_app = TrustedProxyOnly(app.wsgi_app, config.proxy_ip)
    # Existing readiness stays 503 until the deployment root proves all gates.
    return app


def assemble_worker(*, worker_connect, provider_connect, storage_root,
                    cipher, catalogue, principals, concurrency=2, transport_factory=None, enable_blind_jd=False, tenant_research=None, created_after=None):
    """Build a bounded worker without starting it or dispatching AI requests."""
    if not callable(worker_connect) or not callable(provider_connect) or worker_connect is provider_connect:
        raise ValueError("Separate worker and provider connections required")
    verify_service_role(worker_connect, "worker")
    verify_service_role(provider_connect, "provider_reader")
    documents = OnlineDocumentJobs(worker_connect)
    storage = PrivateStorage(storage_root)
    # Transport injection is available only through this trusted Python factory,
    # never through HTTP, config files or the deployed entrypoint.
    provider_options = {} if transport_factory is None else {"transport_factory": transport_factory}
    provider = ProviderConfig(OnlineDocumentJobs(provider_connect), cipher, catalogue, **provider_options)
    return WorkerRuntime(
        principals=principals,
        repository=documents,
        storage=storage,
        workers=WorkerLeases(documents, created_after=created_after),
        ledger=AIBudget(documents),
        outputs=JobOutputs(documents, storage),
        resolve_provider=provider.resolve,
        concurrency=concurrency,
        enable_ocr=False,
        enable_scoring=True,
        enable_blind_jd=enable_blind_jd,
        tenant_research=tenant_research,
    )
