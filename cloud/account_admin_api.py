"""Explicit tenant administration HTTP boundary.

Listing, role changes, suspension/reactivation and session revocation only.
Creation/reset stay internal until secure onboarding and password-change flows
are available. No password, hash or credential retrieval endpoint.
"""
from functools import wraps
import hmac
from flask import jsonify,request
from cloud.auth import TOKEN
from cloud.account_admin import AccountStatus,AccountAdminError
from cloud.documents_jobs import ScopeError

def _public(account):
    if not isinstance(account,AccountStatus):
        raise ValueError("invalid_account")
    return {"user_id":account.user_id,"email":account.email,"role":account.role,
        "active":account.active,"revision":str(account.revision)}

def _revision(value):
    if not isinstance(value,str) or not value.isascii() or not value.isdecimal() or len(value)>19:
        raise ValueError("invalid_revision")
    n=int(value)
    if str(n)!=value or not 1<=n<2**63-1:
        raise ValueError("invalid_revision")
    return n

def register(app,auth,cookie,same_origin,service):
    if not all(callable(getattr(service,k,None)) for k in ("list_accounts","change")):
        raise ValueError("Account service required")
    def protected(*,write=False):
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
                    request.max_content_length=4096
                try:
                    return fn(principal,*args,**kwargs)
                except AccountAdminError as exc:
                    if str(exc)=="account_admin_denied":
                        return jsonify(error="forbidden"),403
                    if str(exc)=="account_conflict":
                        return jsonify(error="account_conflict"),409
                    return jsonify(error="invalid_account_request"),400
                except ScopeError:
                    return jsonify(error="forbidden"),403
                except (ValueError,TypeError):
                    return jsonify(error="invalid_account_request"),400
            return wrapped
        return decorate

    @app.get("/api/admin/accounts")
    @protected()
    def accounts(principal):
        if request.args:
            return jsonify(error="invalid_request"),400
        return jsonify(items=[_public(x) for x in service.list_accounts(principal)])

    @app.post("/api/admin/accounts/<uuid:user_id>/actions")
    @protected(write=True)
    def change(principal,user_id):
        body=request.get_json(silent=True)
        if not isinstance(body,dict):
            return jsonify(error="invalid_request"),400
        action=body.get("action")
        if action=="role_change":
            if set(body)!={"action","expected_revision","value"} or body["value"] not in ("admin","recruiter"):
                return jsonify(error="invalid_request"),400
        elif action in ("suspend","reactivate","revoke_sessions"):
            if set(body)!={"action","expected_revision"}:
                return jsonify(error="invalid_request"),400
        else:
            return jsonify(error="invalid_request"),400
        account=service.change(principal,user_id=str(user_id),expected_revision=_revision(body["expected_revision"]),
            action=action,value=body.get("value"))
        return jsonify(account=_public(account))
