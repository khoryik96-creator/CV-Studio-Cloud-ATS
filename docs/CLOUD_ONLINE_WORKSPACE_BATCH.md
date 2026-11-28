# Online document workspace integration batch

This branch is work in progress and must not be deployed. It reuses the
existing document services and original cloud UI rather than exposing the
synthetic fixture or the legacy desktop server.

## Acceptance checklist for one cohesive PR

- [ ] Apply ordered document, job, output, budget, provider and account
  migrations in an explicitly dedicated online database; record migration
  versions and refuse unmarked databases. Preserve existing authentication.
- [ ] Provision distinct restricted document, admin, provider and worker
  roles. Verify their actual grants and prohibit superuser, role inheritance,
  auth password access and cross-tenant document access.
- [x] Begin internal composition of authenticated CV formatting, blinding,
  scoring, provider settings, account management, usage, history and batch
  controls, using the existing service implementations.
- [ ] Connect that composition to a private, unexposed deployment entry
  point, with explicit operator-supplied provider catalogue and encryption
  keyring. No paid provider request during startup or CI.
- [ ] Implement bounded trusted worker roster discovery and supervision,
  including expiry recovery, graceful shutdown and heartbeat readiness.
- [ ] Mount persistent private document storage with access for web/worker
  only; enforce existing admission limits and plan retention, orphan
  reconciliation and backup/restore.
- [ ] Make UI accurately identify its operational mode; keep unsupported
  Company Profile, Blind JD and Create Profile routes disabled until their
  real adapters are verified. Preserve staging behavior.
- [ ] Exercise end-to-end authenticated upload, queue, worker, output,
  download, scoring, provider configuration and account management on
  disposable infrastructure with explicitly injected test transports.
- [ ] Verify authorization, CSRF, scoped storage, role separation, denial
  of direct requests, disabled modules, quota and restart behavior.
- [ ] Run applicable CI and review before merging. Do not open individual
  PRs for each checklist item.

Later integration: real research and JobAdder adapters; operator approval of
live AI pricing and provider policy; Caddy/DNS/TLS; release acceptance and
rollback. Production readiness remains 503 until verified. No changes to
HyPlug, the private synthetic deployment or public ingress.
