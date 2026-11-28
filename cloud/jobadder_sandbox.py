"""Candidate JobAdder sandbox adapter. Not mounted by the workspace.

The trusted resolver must verify the OAuth account and sandbox designation,
bind a single non-refreshing client to that tenant and revision, and never
accept browser-supplied credentials. A durable attempt guard is required
before any remote write. The workspace attempt journal is available separately; no live resolver is mounted.
"""
from dataclasses import dataclass, field
from contextlib import AbstractContextManager
import json
import re
import secrets
from cloud.auth import Principal
from cloud.documents_jobs import uid, MAX_BYTES
from cloud.private_storage import DOCX

class CRMUnavailable(ValueError):
    pass

@dataclass(frozen=True)
class SandboxSession:
    tenant_id: str
    account_id: str
    revision: int
    sandbox: bool
    client: object = field(repr=False)

def _identifier(value):
    if type(value) is int:
        value=str(value)
    if not isinstance(value,str) or not re.fullmatch(r"[1-9][0-9]{0,18}",value):
        raise CRMUnavailable("Invalid remote identifier")
    return value

class SandboxJobAdder:
    """Explicitly injected client using the existing desktop API contract.

    No automatic refresh, replay, duplicate override, or implicit upload to
    an existing candidate. Uncertain outcomes require manual reconciliation.
    """
    def __init__(self, resolve, attempt_guard):
        if not callable(resolve) or not callable(attempt_guard):
            raise ValueError("Verified sandbox resolver and durable guard required")
        self._resolve=resolve
        self._guard=attempt_guard

    def _session(self, principal):
        if not isinstance(principal,Principal):
            raise CRMUnavailable("Trusted principal required")
        s=self._resolve(principal)
        if (not isinstance(s,SandboxSession) or s.sandbox is not True
                or uid(s.tenant_id)!=uid(principal.tenant_id)
                or not isinstance(s.account_id,str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",s.account_id)
                or type(s.revision) is not int or not 1<=s.revision<2**63
                or not callable(getattr(s.client,"request_json",None))
                or not callable(getattr(s.client,"request_raw",None))):
            raise CRMUnavailable("Verified sandbox connection required")
        return s

    @staticmethod
    def _settings(s):
        return {"account_id":s.account_id,"revision":s.revision,"environment":"sandbox"}

    def settings(self,principal):
        return self._settings(self._session(principal))

    def create_with_cv(self,principal,job_id,settings,candidate,raw,mime,*,lease_token):
        # Validate all local inputs before the first network request.
        job_id=uid(job_id)
        lease_token=uid(lease_token)
        if not isinstance(candidate,dict) or set(candidate)!={"name","email"}:
            raise CRMUnavailable("Reviewed candidate required")
        name,email=candidate["name"],candidate["email"]
        if (not isinstance(name,str) or not 1<=len(name)<=200
                or any(ord(c)<32 or ord(c)==127 for c in name)
                or not isinstance(email,str) or len(email)>254
                or not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+",email)):
            raise CRMUnavailable("Invalid candidate identity")
        parts=name.split()
        if len(parts)<2:
            raise CRMUnavailable("Review first and last names before submission")
        suffix={"application/pdf":"pdf",DOCX:"docx"}.get(mime)
        if suffix is None or not isinstance(raw,bytes) or not 1<=len(raw)<=MAX_BYTES:
            raise CRMUnavailable("PDF or DOCX CV required for sandbox upload")
        s=self._session(principal)
        if settings!=self._settings(s):
            raise CRMUnavailable("Integration configuration changed")
        # The caller must provide a durable non-replay guard shared across
        # workers, keyed by tenant/account/job and normalized email.
        guard=self._guard(principal,s.account_id,job_id,email.casefold(),lease_token=lease_token)
        if not isinstance(guard,AbstractContextManager):
            raise CRMUnavailable("Durable attempt guard required")
        with guard:
            options={"timeout":15,"refresh_on_401":False,"safe_to_retry":False,"retries":0}
            try:
                status,found=s.client.request_json("candidates",params={"email":email},fallback=None,**options)
                # Refuse incomplete/ambiguous search responses. A positive
                # result blocks creation, even if exact identity is uncertain.
                if status!=200 or not isinstance(found,dict) or not isinstance(found.get("items"),list):
                    raise CRMUnavailable("Duplicate lookup unavailable")
                total=found.get("totalCount",found.get("total"))
                if type(total) is not int or total<0 or total<len(found["items"]):
                    raise CRMUnavailable("Duplicate lookup incomplete")
                if total or found["items"]:
                    return {"outcome":"duplicate","candidate_id":None,"cv_uploaded":False}
                payload=json.dumps({"firstName":parts[0],"lastName":" ".join(parts[1:]),"email":email},ensure_ascii=False).encode()
                status,result=s.client.request_json("candidates",method="POST",body=payload,
                    headers={"Content-Type":"application/json"},fallback=None,**options)
                if status not in (200,201) or not isinstance(result,dict):
                    raise CRMUnavailable("Candidate creation not confirmed")
                candidate_id=_identifier(result.get("candidateId"))
                boundary="----CVStudioBoundary"+secrets.token_hex(18)
                while boundary.encode() in raw:
                    boundary="----CVStudioBoundary"+secrets.token_hex(18)
                prefix=(f'--{boundary}\r\nContent-Disposition: form-data; name="fileData"; filename="Original_CV.{suffix}"\r\nContent-Type: {mime}\r\n\r\n').encode("ascii")
                body=prefix+raw+f"\r\n--{boundary}--\r\n".encode("ascii")
                response=s.client.request_raw(f"candidates/{candidate_id}/attachments/Resume",method="POST",
                    body=body,headers={"Accept":"application/json","Content-Type":"multipart/form-data; boundary="+boundary},
                    **dict(options,timeout=30))
                if response.status not in (200,201,204):
                    raise CRMUnavailable("CV attachment not confirmed")
                return {"outcome":"created","candidate_id":candidate_id,"cv_uploaded":True}
            except Exception:
                # Never expose remote body, candidate name, email or token.
                raise CRMUnavailable("Sandbox outcome requires review; do not retry") from None

    def reconcile(self,principal,job_id,settings):
        # No guessed reconciliation from email search or a second write.
        if self.settings(principal)!=settings:
            raise CRMUnavailable("Integration configuration changed")
        uid(job_id)
        return None
