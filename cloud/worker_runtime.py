"""Bounded, explicit-owner staging worker. No global principal discovery.

The trusted composition root must supply server-derived owners, policy resolver
and a new bounded-timeout DB connection per transaction. A single process is
limited to 1-4 concurrent jobs, with one active job per owner across SQL claims.
No production entry point, daemon, hard cancellation or global tenant quota.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from collections import deque
from cloud.auth import Principal,ROLES
from cloud.documents_jobs import uid
from cloud.cv_runner import run_claimed

class WorkerRuntime:
    def __init__(self,*,principals,repository,storage,workers,ledger,outputs,resolve_provider,concurrency=2,enable_ocr=False,enable_scoring=False,research=None,create_profile=None):
        if type(concurrency) is not int or not 1<=concurrency<=4 or type(enable_ocr) is not bool or type(enable_scoring) is not bool:
            raise ValueError("Invalid worker limits")
        if not isinstance(principals,(list,tuple)) or not 1<=len(principals)<=100:
            raise ValueError("Trusted bounded owner roster required")
        roster={}
        for p in principals:
            if not isinstance(p,Principal) or p.role not in ROLES:
                raise ValueError("Invalid worker principal")
            key=(uid(p.tenant_id),uid(p.user_id))
            if key in roster:
                raise ValueError("Duplicate worker owner")
            roster[key]=p
        if not callable(resolve_provider):
            raise ValueError("Trusted provider resolver required")
        # Rotate tenants rather than let a tenant with many owners consume
        # every slot on the first pass.
        tenants={}
        for (tenant,_),p in roster.items():
            tenants.setdefault(tenant,deque()).append(p)
        ordered=[]
        while tenants:
            for key in list(tenants):
                ordered.append(tenants[key].popleft())
                if not tenants[key]:
                    del tenants[key]
        self._roster=deque(ordered)
        self._lock=Lock()
        self._concurrency=concurrency
        self.repository=repository;self.storage=storage;self.workers=workers
        self.ledger=ledger;self.outputs=outputs;self.resolve_provider=resolve_provider
        self.enable_ocr=enable_ocr
        if research is not None and not callable(research):
            raise ValueError("Trusted research adapter required")
        self.research = research
        self.create_profile = create_profile
        self._claim_filters = {"cv_only": True}
        if enable_scoring:
            self._claim_filters["include_scoring"] = True
        if research is not None:
            self._claim_filters["include_reports"] = True
        if create_profile is not None:
            self._claim_filters["include_profile"] = True

    def _one(self,p):
        # No claim until configuration is available. Resolver must not make
        # paid calls or disclose secret material in errors/logs.
        try:
            self.workers.expire(p)
            policy,transport=self.resolve_provider(p)
            lease=self.workers.claim(p,**self._claim_filters)
            if lease is None:
                return "idle"
        except Exception:
            return "unavailable"
        if lease.module == "cv_scoring":
            from cloud.scoring_jobs import run_claimed as run_scoring
            return "completed" if run_scoring(principal=p, lease=lease, repository=self.repository,
                storage=self.storage, workers=self.workers, ledger=self.ledger, policy=policy,
                transport=transport) else "review_or_recovery"
        if lease.module in ("blind_jd", "company_profile"):
            from cloud.document_reports import run_claimed as run_report
            return "completed" if run_report(principal=p, lease=lease, repository=self.repository,
                storage=self.storage, workers=self.workers, ledger=self.ledger, policy=policy,
                transport=transport, research=self.research) else "review_or_recovery"
        if lease.module == "create_profile":
            return "completed" if self.create_profile.run_claimed(p, lease, self.workers) else "review_or_recovery"
        return "completed" if run_claimed(principal=p,lease=lease,repository=self.repository,
            storage=self.storage,workers=self.workers,ledger=self.ledger,policy=policy,transport=transport,
            outputs=self.outputs,enable_ocr=self.enable_ocr) else "review_or_recovery"

    def tick(self):
        """One bounded scheduling round; do not overlap rounds in this process."""
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("Scheduling round already running")
        try:
            batch=[]
            for _ in range(min(self._concurrency,len(self._roster))):
                p=self._roster.popleft()
                self._roster.append(p)
                batch.append(p)
            with ThreadPoolExecutor(max_workers=self._concurrency,thread_name_prefix="cvcloud-job") as pool:
                return tuple(pool.map(self._one,batch))
        finally:
            self._lock.release()
