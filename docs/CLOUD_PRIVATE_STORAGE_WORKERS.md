# Private storage and fenced worker milestone

Adds an internal Linux-volume storage adapter with UUID-only object names, bounded reads, structural PDF/DOCX/text preflight, private file permissions, atomic no-overwrite publication and SHA-256 verification. The storage directory must be an operator-controlled private volume. PDF signature and ZIP preflight are not malware scanning or full content validation. Do not expose direct upload/download routes yet. DB registration and filesystem publication are not yet integrated; reconcile orphan objects after uncertain commits rather than deleting on ambiguous errors.

Adds owner-scoped worker lease SQL using SKIP LOCKED, database time, fencing tokens and expiry. A stale worker cannot complete or renew a lease. Expired work goes to needs_review and is not automatically replayed. The scheduler, worker-specific DB role, output persistence, per-tenant fairness, active AI calls, quotas, orchestration and HTTP endpoints are not wired yet. Existing app readiness stays false.

Review before production: validate storage root/mount permissions, quota admission before reading, upload scanning and parser sandboxing, crash reconciliation, retention, encrypted backups, worker-role grants, transaction/concurrency behavior and load tests. No production data, VPS or original repositories modified.
