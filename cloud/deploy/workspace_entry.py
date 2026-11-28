"""Internal candidate startup. No public routing or automatic live AI approval."""
import argparse
from functools import partial
import signal
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

def web():
    from waitress import serve
    config=read_config()
    cipher,catalogue=load_policy()
    app=assemble_workspace(config=config,auth_connect=connection_factory(config),
        document_connect=service_connection("document"),provider_connect=service_connection("provider"),
        storage_root=STORAGE,cipher=cipher,catalogue=catalogue)
    options=server_options()
    options["max_request_body_size"]=MAX_BYTES
    # Keep bounded threads and no forwarded header rewriting. Flask login
    # still imposes the original 4 KiB limit on authentication requests.
    serve(app,host="0.0.0.0",port=8000,**options)

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
            catalogue=catalogue,concurrency=concurrency())
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
