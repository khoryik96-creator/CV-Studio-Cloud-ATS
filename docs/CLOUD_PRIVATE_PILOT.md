# Private VPS browser acceptance — migration, not redevelopment

Goal: bring the existing CV Studio functionality online while preserving
HyPlug. The pilot is not a public release, does not use the existing Caddy
container, does not change DNS, does not use real candidate data, and leaves
live AI and CRM disabled. The public hostname remains cvstudio.hyplug.co.
Use a separate pilot project and volumes. Do not use any HyPlug/staging
project or remove volumes.

## Read-only preflight

On the VPS, inspect available disk/memory, existing compose projects, host
listeners (particularly 18444) and all Docker network subnets:

```sh
docker compose ls
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
free -h
df -h /
ss -lnt
docker network ls -q | xargs -r docker network inspect --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}} {{end}}'
```

Confirm a free host loopback port and unused subnet before proceeding.
Record existing HyPlug container IDs and uptime without restarting anything.
Use a fresh checkout of a reviewed merged revision, not the existing private
staging checkout. Run Compose using the fixed project name cvcloud-private-pilot
and only the workspace and pilot overlay. Generate distinct secrets in a new
mode-0700 root-owned directory outside Git, never overwrite an existing secret.
Mount only the required role secret files. Keep keys and DB passwords securely
backed up; do not post values in chat. Use a fictional model catalogue for this
UI-only pilot. Do not set CVCLOUD_LIVE_AI=operator-approved.

Configure CVCLOUD_PUBLIC_ORIGIN=https://cvstudio.hyplug.co and
CVCLOUD_PILOT_HOST=cvstudio.hyplug.co; reserve CVCLOUD_TRUSTED_PROXY_IP
inside the unused CVCLOUD_INGRESS_SUBNET. Set CVCLOUD_PILOT_PORT=18444
only if available. Set all required secret paths as documented by the base
compose file. Run compose config --quiet before startup.

```sh
compose() { docker compose -p cvcloud-private-pilot -f cloud/deploy/compose.online-workspace.yaml -f cloud/deploy/compose.online-pilot.yaml "$@"; }
compose config --quiet
compose build web
compose up --no-build -d --wait --wait-timeout 240 pilot-proxy
compose ps -a
```

Use the existing owner CLI to create a fictional test organisation with an
interactive strong password. Do not reuse offline credentials for this pilot.
Export only the public pilot CA certificate from the proxy:

```sh
compose exec -T pilot-proxy cat /data/caddy/pki/authorities/local/root.crt > /root/cvcloud-pilot-root.crt
```

Tunnel local Windows port 443 to VPS 127.0.0.1:18444 through SSH. Use a
temporary hosts-file mapping of cvstudio.hyplug.co to 127.0.0.1 and a
disposable browser/profile that trusts only this pilot root CA; never bypass
TLS validation. Verify the root certificate fingerprint over SSH first.
Remove the temporary mapping and trust after acceptance. The existing VPS
Caddy and DNS remain unchanged.

Verify login/logout, upload of fictional documents, module navigation, history,
settings and user isolation. Queue jobs only if intentionally testing admission;
the worker is disabled and jobs will not complete. Verify port is loopback
only and HyPlug containers/functionality are unchanged. /readyz intentionally
remains 503. Stop only the pilot proxy/web/database when finished, preserving
volumes and secrets. No down -v, system prune or shared proxy changes.

## Remaining parity blockers (not optional feature development)

- Connect existing approved AI provider and model in the cloud worker, with
  controlled egress and explicit spending approval. DeepSeek is the current
  cloud adapter; desktop supports additional providers. Establish which of
  those are actually used before porting more.
- Reuse existing Company Profile research provider rather than require manual
  source curation for normal operation. Verify same input/output behavior.
- Reuse existing JobAdder API/OAuth implementation with cloud callback,
  tenant-bound credentials and explicit candidate confirmation. The offline
  sandbox adapter has passed simulated tests but is not mounted; real sandbox
  acceptance and credential/egress approval remain.
- Test original formatting/blinding rules and all workflows with approved
  inputs, and verify backup/restore and rollback. Only then configure the
  shared public reverse proxy and DNS under explicit operator approval.

No actual VPS deployment, DNS edit, provider request or live candidate
operation has been performed by this PR.

## Worker cutover for the existing gated pilot

Use this only for the existing `cvcloud-private-pilot` project after recording its deployed revision, verifying backups and checking the reviewed checkout against its database schema. Keep the outer access gate in place. Configure a separately approved DeepSeek model, verified pricing, encrypted provider credentials and a pilot spending cap before starting the worker. Use fictional documents for initial verification.

The optional egress overlay joins only the worker to an outbound bridge. The application transport uses the fixed DeepSeek TLS endpoint and refuses redirects. The bridge itself is not a network-level destination allowlist. Verify applicable VPS egress policy before attaching it.

From the reviewed pilot checkout, use the protected existing environment file and these project-scoped commands:

```sh
compose_worker() {
  docker compose --env-file /opt/cvstudio-pilot-secrets/pilot.env \
    -p cvcloud-private-pilot \
    -f cloud/deploy/compose.online-workspace.yaml \
    -f cloud/deploy/compose.online-worker-egress.yaml "$@"
}
compose_worker config --quiet
compose_worker build worker
```

Record a fixed UTC instant in the protected pilot environment as `CVCLOUD_WORKER_ADMIT_AFTER` using `YYYY-MM-DDTHH:MM:SSZ`. The worker claims only jobs created strictly after that instant. Keep this value fixed across restarts. Old queued jobs are preserved for a separate decision. Check for any candidate data queued between the chosen cutoff and the initial smoke test.

After confirming the existing database and web dependencies are healthy, start only the worker. The shell override applies the approval to this command without printing credentials:

```sh
CVCLOUD_LIVE_AI=operator-approved compose_worker up --no-deps --no-build -d --wait worker
compose_worker ps worker
```

Submit a new fictional job and verify the output. For rollback use `compose_worker stop worker`. The web service, outer access gate and database are outside the worker start and stop commands.
