"""Internal candidate startup. No public routing or automatic live AI approval."""
import argparse
from functools import partial
import signal
import sys
from threading import Event
from cloud.deploy.online_auth import read_config,connection_factory
from cloud.deploy.online_serve import server_options
from cloud.deploy.online_workspace import assemble_workspace,assemble_worker
from cloud.deploy.workspace_config import load_policy,service_connection,concurrency,require_live_worker_approval
from cloud.deploy.workspace_heartbeat import Heartbeat
from cloud.deploy.workspace_scheduler import WorkspaceScheduler
from cloud.deploy.workspace_roles import verify_service_role
from cloud.private_storage import PrivateStorage
from cloud.documents_jobs import MAX_BYTES

STORAGE="/srv/cvcloud/data"

class StartupError(RuntimeError):
    pass

def startup_step(label, callback):
    try:
        return callback()
    except Exception as error:
        # Fixed stage and exception class only; never include DSN, file
        # contents, credentials, candidate data or arbitrary exception text.
        print("Workspace startup failed:",label,type(error).__name__,file=sys.stderr,flush=True)
        raise StartupError("Workspace startup failed") from None

def build_web():
    config=startup_step("auth-config",read_config)
    cipher,catalogue=startup_step("provider-policy",load_policy)
    auth_connect=connection_factory(config)
    document_connect=startup_step("document-credentials",lambda:service_connection("document"))
    provider_connect=startup_step("provider-credentials",lambda:service_connection("provider"))
    admin_connect=startup_step("admin-credentials",lambda:service_connection("admin"))
    return startup_step("workspace-composition",lambda:assemble_workspace(
        config=config,auth_connect=auth_connect,document_connect=document_connect,
        provider_connect=provider_connect,admin_connect=admin_connect,storage_root=STORAGE,cipher=cipher,catalogue=catalogue,enable_blind_jd=True))

def web():
    from waitress import serve
    app=build_web()
    options=server_options()
    options["max_request_body_size"]=MAX_BYTES
    # Keep bounded threads and no forwarded header rewriting. Flask login
    # still imposes the original 4 KiB limit on authentication requests.
    startup_step("listener",lambda:serve(app,host="0.0.0.0",port=8000,**options))

def worker():
    # No paid requests or queue claims without a separate explicit live gate.
    require_live_worker_approval()
    stop=Event()
    def request_stop(*_):
        stop.set()
    signal.signal(signal.SIGTERM,request_stop)
    signal.signal(signal.SIGINT,request_stop)
    with Heartbeat() as heartbeat:
        cipher,catalogue=load_policy()
        PrivateStorage(STORAGE)
        worker_connect=service_connection("worker")
        provider_connect=service_connection("provider_reader")
        scheduler_connect=service_connection("scheduler")
        for service,connect in (("worker",worker_connect),("provider_reader",provider_connect),("scheduler",scheduler_connect)):
            verify_service_role(connect,service)
        factory=partial(assemble_worker,worker_connect=worker_connect,
            provider_connect=provider_connect,storage_root=STORAGE,cipher=cipher,
            catalogue=catalogue,concurrency=concurrency(),enable_blind_jd=True)
        scheduler=WorkspaceScheduler(scheduler_connect=scheduler_connect,
            runtime_factory=lambda principals:factory(principals=principals))
        while not stop.is_set():
            heartbeat.set("running")
            results=scheduler.tick()
            heartbeat.set("degraded" if "unavailable" in results else "idle")
            stop.wait(2)
        heartbeat.set("stopping")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("service",choices=("web","worker"))
    args=parser.parse_args()
    try:
        {"web":web,"worker":worker}[args.service]()
    except Exception:
        raise SystemExit("Workspace service refused or failed; inspect isolated configuration.") from None

if __name__=="__main__":
    main()
