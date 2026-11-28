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
