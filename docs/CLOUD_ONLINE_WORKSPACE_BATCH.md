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
- [x] Implement private deployment entrypoint with file-mounted provider
  catalogue and keyring. No default live credentials or automatic dispatch.
- [ ] Verify container startup and isolation in CI.
- [ ] Implement bounded trusted worker roster discovery and supervision,
  including expiry recovery, graceful shutdown and heartbeat readiness.
  Bounded identity-only scheduler function/roster contract implemented;
  scheduler grant and refreshable recurring scheduler with cooperative stop
  implemented. Added process-level heartbeat, outer deadline and signal-based
  stop; worker container remains gated and real-DB execution unverified.
- [ ] Mount persistent private document storage with access for web/worker
  only; enforce existing admission limits and plan retention, orphan
  reconciliation and backup/restore. Dedicated volume and 0700 image path
  are defined; persistence and restore acceptance still pending.
- [x] Make UI accurately identify its operational mode; keep unsupported
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

## Internal workspace candidate

The separate compose.online-workspace.yaml defines a new project, separate DB
and document volumes, internal database and ingress networks, and no host
ports. Do not reuse the private synthetic staging project or HyPlug volumes.
It initializes auth, applies the marked workspace migrations, installs the
restricted service roles and starts the existing UI through bounded Waitress.
The web container receives only auth/document/provider-writer credentials.
The worker receives worker/provider-reader/scheduler credentials. Each secret
is mounted individually; no secret values belong in the repository.

The provider catalogue and encryption keyring are explicit JSON files supplied
by the operator, with no implicit price/model defaults. Live worker activation
requires the operator-worker profile and explicit approval flag. Even then,
this candidate has no external egress: **do not enable the live worker** until
a reviewed egress policy, prices, budgets and operator approval are in place.
The process heartbeat updates every five seconds, detects a stale heartbeat
after 20 seconds, and terminates stuck rounds after 660 seconds. Job leases
remain fenced and uncertain external work must not be replayed automatically.
The heartbeat is liveness, not provider or production readiness.

CI reuses the existing online-auth-container job for a disposable candidate
smoke test (no worker started, no paid calls). The test checks private ports,
secret separation, volume permissions, authenticated original UI, upload and
history. New unit tests cover watchdog, keyring/catalogue, live worker gate
and UI mode. Separate PostgreSQL coverage checks grants and queue semantics.
Account administration/usage, research/Blind JD/Create Profile, real worker
end-to-end outputs, retention, backup/restore, external egress and production
readiness remain open. This coherent internal workspace foundation is ready
for CI review, not for shared VPS deployment. Full release acceptance remains
mandatory.
