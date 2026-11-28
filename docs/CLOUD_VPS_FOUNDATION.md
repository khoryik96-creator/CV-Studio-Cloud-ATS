# M5: VPS health-only packaging
This is a deliberately restricted infrastructure smoke target, not staging of the full CV Studio product. The container packages only the default cloud app and its auth policy import. No credentials, DB, worker, data volumes, real accounts, document routes, provider calls, or desktop modules are included. The application must return 503 at /readyz. Do not attach a reverse proxy or public domain to this target.

## Test on a disposable Linux Docker host
From the repository root, with Docker Engine, Compose v2 supporting --wait and curl installed:
```sh
sh cloud/deploy/smoke.sh
```
The script uses a unique project, binds port 18080 only to loopback (override with CVCLOUD_HEALTH_PORT if occupied), tests process identity, read-only root, port binding, health, fail-closed readiness and route absence, then removes its containers. It does not remove images. No production credentials are needed.

For manual private inspection use `docker compose -f cloud/deploy/compose.yaml up --build -d --wait` and `curl http://127.0.0.1:18080/healthz`; stop with `docker compose -f cloud/deploy/compose.yaml down`. Do not route customer traffic here. Limits (0.5 CPU and 256 MiB) are preliminary smoke-test limits, not workload sizing. The base image tag and transitive Python packages are not digest/hash locked yet.

## Next gates
Separate persistent PostgreSQL and migration/auth/worker roles; private storage with tested restore; containerize a synthetic-only functional composition; verify original UI and worker end-to-end; configure shared HTTPS proxy with exact origin and trusted forwarding policy; test isolation, backup and rollback with fictional data; pin release images and dependencies; measure resource headroom. No production deployment until M6 and operator approval.
