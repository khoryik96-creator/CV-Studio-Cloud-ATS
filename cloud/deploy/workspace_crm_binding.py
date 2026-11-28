"""Bind trusted OAuth exchange results to operator-approved sandbox identities.

No OAuth callback, token persistence, automatic refresh or actual exchange
is exposed here. Only a trusted server-side exchange may supply its response.
The approved sandbox account list must be verified independently by the
operator; an OAuth token response does not prove sandbox status.
"""
from dataclasses import dataclass
from urllib.parse import urlsplit
from time import time
import re
from cloud.documents_jobs import uid
from cloud.jobadder_sandbox import SandboxSession,CRMUnavailable
from cvstudio_clients import JobAdderClient

def api_base(value):
    if not isinstance(value,str) or len(value)>256:
        raise CRMUnavailable("Invalid JobAdder API base")
    p=urlsplit(value)
    if (p.scheme!="https" or not p.hostname or not p.hostname.endswith(".jobadder.com")
            or p.netloc!=p.hostname or p.path.rstrip("/")!="/v2" or p.query or p.fragment
            or any(c.isspace() or c=="\\" for c in value)):
        raise CRMUnavailable("Invalid JobAdder API base")
    return "https://"+p.hostname+"/v2"

@dataclass(frozen=True)
class ApprovedSandbox:
    tenant_id: str
    instance: str
    account: int
    api: str
    revision: int

    def __post_init__(self):
        object.__setattr__(self,"tenant_id",uid(self.tenant_id))
        if (not isinstance(self.instance,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}",self.instance)
                or type(self.account) is not int or not 1<=self.account<2**63
                or type(self.revision) is not int or not 1<=self.revision<2**63):
            raise ValueError("Invalid approved sandbox identity")
        object.__setattr__(self,"api",api_base(self.api))

    @property
    def account_id(self):
        return self.instance+"-"+str(self.account)

class SandboxBindings:
    def __init__(self,approved,*,clock=time,client_factory=JobAdderClient):
        if not isinstance(approved,(tuple,list)) or not 1<=len(approved)<=100:
            raise ValueError("Explicit approved sandbox identities required")
        self._approved={}
        seen=set()
        for row in approved:
            if not isinstance(row,ApprovedSandbox) or row.tenant_id in self._approved or row.account_id in seen:
                raise ValueError("Duplicate or invalid sandbox binding")
            seen.add(row.account_id)
            self._approved[row.tenant_id]=row
        self._clock=clock
        self._client=client_factory

    def bind(self,principal,response,*,received_at):
        # Only the trusted OAuth backend supplies response and receipt time.
        # Never accept an OAuth response posted by the browser.
        from cloud.auth import Principal
        if not isinstance(principal,Principal):
            raise CRMUnavailable("Trusted principal required")
        approved=self._approved.get(uid(principal.tenant_id))
        if approved is None or not isinstance(response,dict):
            raise CRMUnavailable("No approved sandbox binding")
        try:
            matches=(response["instance"]==approved.instance
                and type(response["account"]) is int and response["account"]==approved.account
                and api_base(response["api"])==approved.api)
            token=response["access_token"]
            expires=response["expires_in"]
            age=self._clock()-received_at
            if (not matches or response["token_type"].casefold()!="bearer"
                    or not isinstance(token,str) or not 16<=len(token)<=16384
                    or any(c.isspace() or ord(c)<33 or ord(c)>126 for c in token)
                    or type(expires) is not int or not 1<=expires<=3600
                    or not 0<=age<expires-120):
                raise CRMUnavailable("Sandbox account mismatch or token unavailable")
        except (KeyError,TypeError,ValueError,AttributeError):
            raise CRMUnavailable("Sandbox account mismatch or token unavailable") from None
        deadline=received_at+expires
        def pinned_token(force=False):
            # Never return a different account or refresh a write in flight.
            if force or self._clock()>=deadline:
                return ""
            return token
        client=self._client(lambda:approved.api,pinned_token)
        return SandboxSession(approved.tenant_id,approved.account_id,approved.revision,True,client)
