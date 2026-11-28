"""Trusted sandbox broker lifecycle. Not mounted in a web route.

The caller supplies authenticated server principals, a verified approved
sandbox binding and the trusted token exchange function. No automatic replay
of uncertain exchanges; refresh rotation is committed before exposing a
session. In-flight CRM writes must later share a broker-side dispatch fence.
"""
from hashlib import sha256
from hmac import compare_digest
from secrets import token_urlsafe
from time import time
from urllib.parse import urlencode,urlsplit
from cloud.auth import Principal
from cloud.documents_jobs import uid
from cloud.jobadder_sandbox import CRMUnavailable

AUTHORIZE="https://id.jobadder.com/connect/authorize"

def token_text(value,limit=16384):
    if (not isinstance(value,str) or not 1<=len(value)<=limit
            or any(ord(c)<33 or ord(c)>126 for c in value)):
        raise CRMUnavailable("Invalid OAuth value")
    return value

def digest(value):
    return sha256(token_text(value).encode("ascii")).hexdigest()

class SandboxOAuth:
    def __init__(self,vault,bindings,exchange,*,client_id,client_secret,redirect_uri,scope,clock=time):
        self.vault=vault
        self.bindings=bindings
        self.exchange=exchange
        self.client_id=token_text(client_id,256)
        self._secret=token_text(client_secret,4096)
        p=urlsplit(redirect_uri)
        if (p.scheme!="https" or p.netloc!=p.hostname or not p.hostname
                or p.path!="/api/admin/jobadder/callback" or p.query or p.fragment):
            raise ValueError("Exact registered HTTPS callback required")
        self.redirect_uri=redirect_uri
        if not isinstance(scope,str) or not scope or len(scope)>512 or any(not s.replace("_","").isalnum() for s in scope.split()):
            raise ValueError("Explicit OAuth scope required")
        self.scope=scope
        self.clock=clock

    def _owner(self,p):
        if not isinstance(p,Principal) or p.role!="owner":
            raise CRMUnavailable("Owner approval required")
        return uid(p.tenant_id),uid(p.user_id),digest(p.csrf)

    def begin(self,p):
        tenant,user,session=self._owner(p)
        state=token_urlsafe(32)
        with self.vault.locked(tenant) as (row,save):
            # Existing authorization must be explicitly disconnected before
            # replacement. Never overwrite a potentially active connection.
            if row["state"] not in ("disconnected","reconnect_required","pending"):
                raise CRMUnavailable("Disconnect or resolve existing authorization first")
            save({"revision":row["revision"]+1,"state":"pending","owner":user,
                "session":session,"state_digest":digest(state),"expires":self.clock()+300})
        return AUTHORIZE+"?"+urlencode({"response_type":"code","client_id":self.client_id,
            "redirect_uri":self.redirect_uri,"scope":self.scope,"state":state})

    def _accept(self,p,row,response,received,save):
        # Binding checks actual token response account/instance/API against
        # approved sandbox allowlist. Never trust account data from browser.
        session=self.bindings.bind(p,response,received_at=received)
        refresh=token_text(response.get("refresh_token"))
        access=token_text(response.get("access_token"))
        safe={k:response[k] for k in ("instance","account","api","token_type","expires_in")}
        safe.update(access_token=access,refresh_token=refresh)
        save({"revision":row["revision"],"state":"connected","response":safe,
              "received":received})
        from dataclasses import replace
        return replace(session,revision=row["revision"])

    def complete(self,p,*,state,code):
        tenant,user,session=self._owner(p)
        code=token_text(code,4096)
        with self.vault.locked(tenant) as (row,save):
            if (row["state"]!="pending" or row.get("owner")!=user
                    or not compare_digest(row.get("session",""),session)
                    or not compare_digest(row.get("state_digest",""),digest(state))
                    or self.clock()>=row.get("expires",0)):
                raise CRMUnavailable("OAuth state invalid, expired or already used")
            # Persist consumed state before token exchange. If the broker
            # crashes, no later callback may replay the code.
            revision=row["revision"]
            save({"revision":revision,"state":"exchanging"})
            try:
                received=self.clock()
                response=self.exchange({"grant_type":"authorization_code","code":code,
                    "redirect_uri":self.redirect_uri,"client_id":self.client_id,"client_secret":self._secret})
                return self._accept(p,row,response,received,save)
            except Exception:
                save({"revision":revision,"state":"reconnect_required"})
                raise CRMUnavailable("OAuth exchange not confirmed; reconnect required") from None

    def resolve(self,p):
        if not isinstance(p,Principal):
            raise CRMUnavailable("Authenticated principal required")
        tenant=uid(p.tenant_id)
        with self.vault.locked(tenant) as (row,save):
            if row["state"]!="connected":
                raise CRMUnavailable("Sandbox connection unavailable")
            from dataclasses import replace
            response=row["response"]
            if self.clock()-row["received"]<response["expires_in"]-120:
                return replace(self.bindings.bind(p,response,received_at=row["received"]),revision=row["revision"])
            # A rotating refresh token must never be replayed after an
            # ambiguous crash or network error. Consume it durably first.
            save({"revision":row["revision"],"state":"refreshing"})
            try:
                received=self.clock()
                new=self.exchange({"grant_type":"refresh_token","refresh_token":response["refresh_token"],
                    "client_id":self.client_id,"client_secret":self._secret})
                return self._accept(p,row,new,received,save)
            except Exception:
                save({"revision":row["revision"],"state":"reconnect_required"})
                raise CRMUnavailable("Refresh not confirmed; owner must reconnect") from None

    def disconnect(self,p):
        tenant,_,__=self._owner(p)
        with self.vault.locked(tenant) as (row,save):
            save({"revision":row["revision"]+1,"state":"disconnected"})

    def status(self,p):
        if not isinstance(p,Principal):
            raise CRMUnavailable("Authenticated principal required")
        with self.vault.locked(uid(p.tenant_id)) as (row,_):
            return {"state":row["state"],"revision":row["revision"]}
