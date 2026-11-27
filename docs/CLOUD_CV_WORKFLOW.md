# M1: authenticated CV vertical slice (staging only)

Adds opt-in raw binary upload, job submission, status and attachment download endpoints; same-origin CSRF for mutations, owner/tenant scope, body size limits, no user-chosen file paths or provider credentials. Only formatting and blinding can be submitted. The default app still exposes health endpoints only and readiness remains false.

Upload admission serializes per-user registered input size/count limits (256 MiB/100 files, initial conservative defaults). File bytes precede DB commit; uncertain commits may leave orphan files. These are not tenant-wide physical disk quotas. A review-required result can be explicitly downloaded for human review using ?review=1; this is not an approval or external sharing action. Review resolution, retention, history and batch UI remain pending.

Persists job options and verifies them on idempotent resubmission. A claimed-job adapter loads stored options, executes the budgeted engine and publishes immutable output. Unknown failures go to needs_review if the lease remains valid. No automatic retry. No live provider setup, scheduler, continuous heartbeat, hardened parser sandbox, real production HTTP startup or VPS deployment. Tests use fictional data and fake provider.
