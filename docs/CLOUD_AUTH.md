# Cloud identity milestone (not production-ready)

This is a stacked milestone on the Word parity branch. It adds a server-side session service, PostgreSQL auth storage adapter and migration, and optional login/me/logout HTTP routes. Default boot exposes only health and deliberately failing readiness. No desktop app is imported. No live database or secrets are provisioned.

The design uses tenant-specific accounts, scrypt password hashes, opaque session tokens (only SHA-256 digests persisted), eight-hour expiry, live account/role checking, Secure HttpOnly SameSite=Strict host-only cookies, exact HTTPS host/origin and CSRF on logout. Login attempts are limited per account and source using atomic fixed-window buckets. Tests use fictional accounts.

Before enabling real logins: provision a separate database and migration/runtime roles, add psycopg dependency and secure configuration, verify the migration and concurrent transactions against PostgreSQL, implement owner provisioning/password reset/session revocation, audit events, configure trusted reverse proxy client IP and upstream global limits, schedule expired-row cleanup, and validate HTTPS/cookies. The injected auth routes do not trust X-Forwarded-For. No user-supplied tenant ID can be used as document authorization: future repositories must enforce the principal's tenant and ownership on every query. RLS and cross-tenant document tests remain pending.

No production deployment or legacy module deletion. Readiness remains false until secure document services exist.
