"""Restricted sandbox service candidate; deliberately not mounted in HTTP."""
from cloud.create_profile import CreateProfile
from cloud.jobadder_sandbox import SandboxJobAdder
from cloud.documents_jobs import ScopeError

class SandboxCreateProfile(CreateProfile):
    def __init__(self, repository, storage, jobadder):
        if not isinstance(jobadder,SandboxJobAdder):
            raise ValueError("Verified sandbox adapter required")
        super().__init__(repository,storage,jobadder)

    def _read(self,principal,document_id):
        candidate,raw,mime,digest=super()._read(principal,document_id)
        from cloud.private_storage import DOCX
        if mime not in ("application/pdf",DOCX) or len(candidate["name"].split())<2:
            raise ValueError("Review candidate name and use PDF or DOCX")
        return candidate,raw,mime,digest

    def _dispatch(self,principal,lease,settings,candidate,raw,mime):
        return self.jobadder.create_with_cv(principal,lease.job_id,settings,candidate,raw,mime,
            lease_token=lease.token)

    def reconcile(self,principal,job_id):
        # Web admission role must never acquire state/result UPDATE rights.
        # A future read-only remote evidence verifier can be introduced with
        # separate reviewed grants. Never retry or infer success from email.
        raise ScopeError("Manual sandbox reconciliation required")
