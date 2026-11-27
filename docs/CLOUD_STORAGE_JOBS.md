# Storage and job queue foundation

Adds owner- and tenant-scoped document metadata and durable job records, explicit composite foreign keys and forced row-level security. No real document bytes or secrets are stored yet. Every repository operation derives scope from a server-resolved Principal, uses transaction-local PostgreSQL settings, and applies explicit tenant/owner query filters. The DB runtime role must be separate from migrations, have no BYPASSRLS, and must not be exposed to arbitrary SQL. The app has no upload/job HTTP endpoints yet.

Enqueue checks module selection and ownership, serializes per-account admission, caps outstanding jobs at 10 per account and uses an idempotency key. Reusing a key for a different operation is rejected. Workers will claim with a lease/fencing token; the pure state policy explicitly refuses automatic replay when a potentially paid operation has an uncertain outcome. No worker claims or transitions are wired yet.

Next: private storage service with bounded validated uploads, atomic creation and orphan reconciliation; tenant-wide quotas, worker claim/heartbeat/expiry SQL with fenced completion; AI provider accounting; real authenticated endpoints; role-specific privileges; retention/deletion and offsite backup.

Integration tests use disposable PostgreSQL and an unprivileged test runtime role. Broad test grants are not production grants; production grants must be narrowed. Do not run against HyPlug or any persistent database.
