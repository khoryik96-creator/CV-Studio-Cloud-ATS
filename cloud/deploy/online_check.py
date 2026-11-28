"""Internal liveness/auth database check, not production readiness."""
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler, Request
from urllib.parse import urlsplit
from cloud.deploy.online_auth import read_config,connection_factory,verify_database

def main():
    cfg=read_config()
    verify_database(connection_factory(cfg))
    request=Request("http://127.0.0.1:8000/healthz",headers={"Host":urlsplit(cfg.origin).hostname})
    try:
        with build_opener(ProxyHandler({})).open(request,timeout=3):
            pass
    except HTTPError as error:
        if error.code==403:
            return
    raise SystemExit("Auth listener must reject requests outside trusted ingress")

if __name__=="__main__":
    main()
