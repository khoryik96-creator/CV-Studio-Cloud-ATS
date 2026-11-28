# Online CV Studio — authentication foundation (not a public release)

Target: https://cvstudio.hyplug.co. Leave the current fictional staging service
and the HyPlug project, Caddy and database untouched. This branch implements
an auth-only factory, not a running web service; it does not expose the UI,
document routes or live providers. Production readiness intentionally returns 503.

## Trust and provisioning
Use a new CV Studio Compose project, isolated network and separate PostgreSQL
database named cvcloud_online. Do not reuse the fixture or HyPlug database.
The future DB service name is online-db; create a non-owner cvcloud_auth
LOGIN role without role memberships or privileged attributes and a generated
password. Apply 001_auth.sql and 004_auth_epoch.sql as a separate schema owner,
then online_auth_grants.sql. Only the owner/controlled provisioning process
may create users; no default accounts, known fixture passwords or public
registration. Keep the password in a restricted mounted file, not Git or
command-line arguments. The auth role can read authentication records and
write sessions/rate limits but cannot directly modify users or tenants.
The narrow security-definer account lock must be owned by the schema owner.

Configuration: CVCLOUD_PUBLIC_ORIGIN=https://cvstudio.hyplug.co,
CVCLOUD_TRUSTED_PROXY_IP=<actual dedicated ingress peer IP>,
CVCLOUD_AUTH_PASSWORD_FILE=<absolute secret mount path>.
The factory refuses direct traffic and ambiguous forwarded IPs. The future
WSGI server must preserve the raw socket peer and forwarding headers for
this middleware. Caddy must overwrite X-Forwarded-For and X-Forwarded-Proto
with the actual client and HTTPS scheme, preserve the exact Host, and connect
through an isolated network with a fixed/verified peer; never trust arbitrary
forwarded headers or publish a backend port. No change to existing Caddy
routes until a reviewed candidate, TLS validation and rollback plan exist.

## Remaining
Real PostgreSQL restricted-role and concurrency tests; operator owner
provisioning and password reset; production WSGI/Compose and Caddy integration;
authenticated UI and six real service compositions; live provider catalogue,
budget and secret controls; real JobAdder sandbox/approval; parser isolation,
retention, load, recovery and security acceptance. Do not publish the existing
synthetic fixture to this hostname. No production deployment from this PR.
