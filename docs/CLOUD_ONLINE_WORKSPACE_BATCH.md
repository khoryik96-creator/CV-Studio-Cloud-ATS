# Online document workspace integration batch

This branch is work in progress and must not be deployed. It reuses the
existing document services and original cloud UI rather than exposing the
synthetic fixture or the legacy desktop server.

Current branch: einstein/online-workspace-batch, based on the merged CI policy.
Previous einstein/online-document-workspace branch is retained as history only.
No public entry point, provider calls or VPS operations are authorized.

## Acceptance checklist for one cohesive PR

- [x] Implement ordered transactional workspace migration extension with recorded
  SHA-256 history and marked-auth-schema guard. No real database has been migrated.
- [ ] Verify migrations and repeat initialization in disposable PostgreSQL.
- [ ] Provision distinct restricted document, admin, provider and worker
  roles. Verify their actual grants and prohibit superuser, role inheritance,
  auth password access and cross-tenant document access. Startup guard and
  role identity checks, narrow account-lock helper, and explicit document,
  worker, provider writer/reader and scheduler grants implemented. Account
  administration grants and their separate authorization boundary remain open.
- [x] Begin internal composition of authenticated CV formatting, blinding,
  scoring, provider settings, history and batch controls using the existing
  services. Account management and usage are deliberately disabled until
  restricted grants are ready.
- [ ] Connect that composition to a private, unexposed deployment entry
  point, with explicit operator-supplied provider catalogue and encryption
  keyring. No paid provider request during startup or CI.
- [ ] Implement bounded trusted worker roster discovery and supervision,
  including expiry recovery, graceful shutdown and heartbeat readiness.
  Bounded identity-only scheduler function/roster contract implemented;
  scheduler grant and refreshable recurring scheduler with cooperative stop
  implemented. Daemon entrypoint, heartbeat, and real-DB execution remain.
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

## Restricted data roles checkpoint

The operator-only workspace_grant_install module provisions five standalone
roles in the marked online database; it does not rotate existing credentials.
The document role may admit inputs and jobs, not complete jobs. The worker
can claim and settle jobs but cannot change the budget ceiling or account
credentials. The provider writer cannot read ciphertext; the provider reader
cannot modify settings. The scheduler gets only active identities (maximum
100; overflow fails closed). Account write grants remain intentionally absent.
Row locks use the schema owner's narrow security-definer function in online
repositories, rather than UPDATE privileges on accounts or tenants.
RLS relies on server-resolved transaction-local tenant/owner identity; these
roles are trusted backend roles, not end-user SQL connections. This does not
make a compromised runtime database credential safe. Real CRM fixture tables
remain ungranted and inaccessible to these roles.

A disposable Linux CI PostgreSQL test has been added for repeat migration and
grant installation, cross-tenant reads, forbidden column writes, provider
writer/reader separation, upload, lease, budget and queue history. It uses
only an injected fictional transport and is not yet executed. No live secrets,
provider calls, database changes or VPS deployment have occurred. Continue
with reviewed account administration, private volume/entrypoint and worker
heartbeat, then test the whole batch under the change-aware CI policy.
