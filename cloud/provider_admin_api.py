"""Opt-in administrative settings API. No credential retrieval or paid test calls."""
from functools import wraps
from flask import request,jsonify
import hmac
from cloud.auth import TOKEN
from cloud.provider_config import ProviderConfigError,ProviderStatus
from cloud.documents_jobs import ScopeError

def _public(status):
    if status is None:
        return {"revision":"0","provider":None,"model":None,"enabled":False}
    if not isinstance(status,ProviderStatus):
        raise ValueError("invalid_configuration")
    # Serialize revisions as decimal strings so JS cannot lose bigint precision.
    return {"revision":str(status.revision),"provider":status.provider,
        "model":status.model,"enabled":status.enabled}

def _revision(value):
    if not isinstance(value,str) or not value.isascii() or not value.isdecimal() or len(value)>19:
        raise ValueError("invalid_revision")
    n=int(value)
    if str(n)!=value or not 0<=n<2**63-1:
        raise ValueError("invalid_revision")
    return n

def register(app,auth,cookie,same_origin,service):
    if not all(callable(getattr(service,k,None)) for k in ("status","choices","configure","disable")):
        raise ValueError("Invalid provider administration service")
    def protected(write=False):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                principal=auth.principal(request.cookies.get(cookie))
                if principal is None:
                    return jsonify(error="unauthorized"),401
                if principal.role not in ("owner","admin"):
                    return jsonify(error="forbidden"),403
                if write:
                    csrf=request.headers.get("X-CSRF-Token","")
                    if not same_origin() or not TOKEN.fullmatch(csrf) or not hmac.compare_digest(principal.csrf,csrf):
                        return jsonify(error="forbidden"),403
                    request.max_content_length=24576
                try:
                    return fn(principal,*args,**kwargs)
                except ProviderConfigError as exc:
                    if str(exc)=="provider_access_denied":
                        return jsonify(error="forbidden"),403
                    if str(exc)=="configuration_conflict":
                        return jsonify(error="configuration_conflict"),409
                    return jsonify(error="invalid_configuration"),400
                except ScopeError:
                    return jsonify(error="forbidden"),403
                except (ValueError,TypeError):
                    return jsonify(error="invalid_configuration"),400
            return wrapped
        return decorate

    @app.get("/api/admin/ai-provider")
    @protected()
    def status(principal):
        return jsonify(configuration=_public(service.status(principal)),
            choices=[{"provider":p,"model":m} for p,m in service.choices(principal)])

    @app.post("/api/admin/ai-provider")
    @protected(write=True)
    def configure(principal):
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"provider","model","secret","expected_revision"}:
            return jsonify(error="invalid_request"),400
        revision=_revision(body["expected_revision"])
        # Never return submitted content or exception messages.
        value=service.configure(principal,provider=body["provider"],model=body["model"],
            secret=body["secret"],expected_revision=revision)
        return jsonify(configuration=_public(value))

    @app.post("/api/admin/ai-provider/disable")
    @protected(write=True)
    def disable(principal):
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)!={"expected_revision"}:
            return jsonify(error="invalid_request"),400
        value=service.disable(principal,expected_revision=_revision(body["expected_revision"]))
        return jsonify(configuration=_public(value))
