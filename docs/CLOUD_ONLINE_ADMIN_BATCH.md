# Next consolidated online batch: administration and acceptance

Development branch based on merged master; no PR until PR #51 is green
and merged, then incorporate that exact reviewed base. Do not deploy.

Implemented candidate SQL security-definer functions for tenant-scoped
account listing, role/suspension/reactivation changes, session revocation
and read-only budget snapshot. The functions recheck the active actor,
lock tenant then target, prohibit self/owner changes, enforce revisions,
revoke sessions, and audit changes in the same transaction. No direct
table access, password reset, invitation or account creation grants.
The backend role still relies on trusted server-derived transaction scope;
never expose raw database credentials to a browser. Candidate Python
adapters and unit tests are committed, not yet executed.

Remaining: review role installation, positive and negative grants checks,
real disposable PostgreSQL tests (including concurrent login/revocation,
cross-tenant and stale revision), wire into candidate Compose and UI after
PR #51 merges. Add operator-only budget provisioning with explicit pricing
and spend controls, and complete end-to-end worker tests using injected
fictional transport before any live egress or provider approval. No real
candidate data, live external calls or production routing.

Added transactional admin role installation tied to exact workspace migration and grant signatures, with explicit denial of direct table/column access and internal lock-helper execution. Prepared a reusable disposable PostgreSQL acceptance helper for tenant isolation, forbidden direct SQL, role restrictions, suspension/reactivation, stale revision and audit checks. It is not wired into CI yet: integrate with the merged #51 disposable database lifecycle, including safe cleanup of the added role. Session concurrency and real worker output testing remain open.

## Combined administration and worker acceptance candidate

PR #51 is merged at a0fd00d55b70918a242bb1f8b1447e9d0cc2e76b. Current branch einstein/online-admin-worker-batch carries forward the earlier candidate and integrates the function-only admin role installer, startup verification, admin/usage APIs and original UI. The web container alone receives the admin role credential; worker receives no admin credential. The private Compose smoke now exercises authenticated account listing and usage. The disposable DB lifecycle includes role cleanup, actual session revocation and a concurrent stale-credential login race. Worker acceptance uses the real restricted worker assembly, original fictional CV/JD fixtures and an explicitly injected in-process transport, with formatting, blinding, scoring and owner-scoped output tests. No live network calls or secrets. These additions are unverified until CI runs; do not deploy or expose publicly. Account creation/invites, password reset, operator budget provisioning, real provider egress, research and CRM remain open. The next acceptance gates are exact-head CI, review, backup/restore and explicit operator approval before enabling live provider processing.
