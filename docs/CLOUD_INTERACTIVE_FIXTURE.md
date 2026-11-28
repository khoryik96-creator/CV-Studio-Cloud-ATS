# Interactive synthetic-only staging
Use a disposable Docker host for the automated smoke test. For manual private staging on an approved shared VPS, follow the procedure below. Run `sh cloud/deploy/interactive-smoke.sh` for a real HTTPS, PostgreSQL, session, automatic worker, preview, and Word-output smoke test. The database, worker and seed stay on the internal network. The web service publishes HTTPS only on host loopback through an ingress bridge with masquerading disabled. AI and JobAdder do not make live calls. The smoke test recreates its containers, verifies that job history, preview, and Word downloads survive, and removes its unique project's volumes on exit.

For private manual use, start a distinct project with `docker compose -p cvcloud-local-fixture -f cloud/deploy/compose.interactive.yaml up --build -d`. Port 443 on localhost must be free; add cv.example.test to the local hosts file pointing at 127.0.0.1. Export the local synthetic certificate using `docker compose -p cvcloud-local-fixture -f cloud/deploy/compose.interactive.yaml exec -T web cat /tmp/cvcloud.crt > ./cvcloud-local.crt`; trust only this certificate for the local test origin in a disposable browser profile, never bypass TLS checks. It changes when the web process restarts. Open https://cv.example.test/cloud-ui with organisation fictional, email synthetic@example.test and password fictional-staging-only-123. Use the bundled fictional files under tests/fixtures. Use Format or Blind on the fixture, or add copies of the fixture in Batch. Blinded previews and Word files require acknowledgment for human review. For CV Scoring, use cloud_cv_source.txt and cloud_cv_scoring_jd.txt. Enter one or both of the exact requirements from the last two lines of the JD. Reports show source evidence and remain available in Recent assessments. For Company Profile, enter Fictional Harbour Labs to see a briefing with citations from the fictional research adapter. For Blind JD, use cloud_cv_blind_jd.txt, enter Fictional Harbour Labs as an employer identifier, and enter Ansible as a technology to retain. For Create Profile, upload cloud_cv_source.txt, review the name and email, and explicitly confirm. The mocked JobAdder account stores the fictional upload and blocks duplicates. Recent JobAdder history includes confirmation and attempts. Outcome reconciliation only reads the mock record. The development TLS server is explicitly not production infrastructure; /readyz stays 503.

Named DB and private file volumes survive container recreation. Initialization commits the role, migrations, accounts, and marker together, so interrupted initialization can be retried. The seed refuses unmarked schemas or changed migration signatures. Use a new disposable project for changed migrations. Stop and remove only this project's synthetic volumes with `docker compose -p cvcloud-local-fixture -f cloud/deploy/compose.interactive.yaml down --volumes`. Runtime uses a separate non-superuser DB role with existing test grants, not final production least privilege. Worker launches bounded subprocess rounds and relies on fenced expiry recovery; production isolation, hard cancellation of all arbitrary descendants, browser test in containers, and six-module coverage remain gates.

## Private VPS staging and recovery

Run this fixture on a disposable host first. Its readiness endpoint is `/staging-readyz`, which returns 503 when its database, document directory, or worker heartbeat is unavailable. Production readiness remains 503.

For an approved VPS test, first compare measured CPU, memory and free disk with the existing HyPlug load. The steady-state CV Studio service memory limits total 2.75 GiB (768 MiB DB and 1 GiB each for web and worker), with a separate 1 GiB seed container during initialization. Allow additional space for image pulls, databases, documents and backups. Capture `free -h`, `df -h`, `docker stats --no-stream` and `ss -ltn` on the VPS before choosing limits or a port. Keep the separate Compose project and volumes. Use an approved commit and rerun the smoke test on an isolated host.

Check the Docker server version with `docker version --format '{{.Server.Version}}'`. Use Docker Engine 28.0.0 or later with standard NAT bridge networking and no direct routing to the fixture networks. Earlier releases can expose loopback-published ports to peers on the same layer-2 network. If the host does not meet these conditions, stop before starting the stack and arrange a separate maintenance decision. [Docker port publishing](https://docs.docker.com/engine/network/port-publishing/)

On the VPS, use a unique Compose project and verify that TCP port 18443 is free. The fixture creates its own networks, PostgreSQL container and named database and document volumes. Only the web container publishes a port. Keep Caddy's configuration, the firewall and HyPlug's Compose resources outside this procedure. Access to the host or its Docker daemon is trusted because the fixture uses known synthetic credentials.

From the approved checkout, use the existing local images. If `postgres:16` is missing, pull that image first with `docker pull postgres:16`.

```sh
export CVCLOUD_FIXTURE_PORT=18443
compose() { docker compose -p cvcloud-staging -f cloud/deploy/compose.interactive.yaml "$@"; }
compose config --quiet
compose config   # Check the web binding is 127.0.0.1:18443 -> 8443.
compose up --no-build --pull never -d --wait --wait-timeout 180
compose ps
compose port web 8443
```

The port command should print `127.0.0.1:18443`. Check HTTPS readiness on the VPS with the certificate served by the fixture.

```sh
cert=$(mktemp)
compose exec -T web cat /tmp/cvcloud.crt > "$cert" &&
  curl --fail --silent --show-error --max-time 10 --noproxy '*' \
    --resolve cv.example.test:18443:127.0.0.1 --header 'Host: cv.example.test' \
    --cacert "$cert" https://cv.example.test:18443/staging-readyz
rm -f "$cert"
```

For owner testing, forward local port 443 to VPS loopback port 18443 with `ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:443:127.0.0.1:18443 user@vps-host`. Map `cv.example.test` to local loopback and trust the certificate obtained over SSH for that test origin. Open `https://cv.example.test/cloud-ui` and use the fictional files. To stop staging while preserving its data, run `compose stop` with the same project and file. A public release uses a dedicated domain, managed TLS, its own credentials and separate release approval.

Use a restricted backup directory outside the checkout. Quiesce the web and worker before capturing both parts of the same backup. For example, from a shell in the approved checkout:

```sh
export CVCLOUD_FIXTURE_PORT=18443
compose() { docker compose -p cvcloud-staging -f cloud/deploy/compose.interactive.yaml "$@"; }
umask 077
backup_dir=/path/to/private/cvcloud-backup
mkdir -p "$backup_dir"
compose stop web worker
compose exec -T db pg_dump -U postgres -d cvcloud_test --format=custom > "$backup_dir/database.dump"
compose run --no-deps --rm -T --entrypoint tar web \
    -C /srv/cvcloud/data --exclude=.fixture-worker-heartbeat -czf - . > "$backup_dir/documents.tar.gz"
compose up -d --wait
```

Restore only trusted backups to a **new** project. Use the backed-up source revision, a distinct project name and a free loopback port. Start only `db`, create the fixture runtime role, then use `pg_restore -U postgres -d cvcloud_test --single-transaction --exit-on-error --no-owner` inside that service. Restore the private archive into the new document volume with `compose run --no-deps --rm -T --entrypoint tar web --no-same-owner -C /srv/cvcloud/data -xzf -`. Start the project, verify readiness, sign in, inspect historical results and process a new job. The exact commands are exercised by `sh cloud/deploy/interactive-smoke.sh --verify-restore`.

For rollback, stop the candidate project and bring the last verified revision up under its own project name and volumes. When a schema signature changed, restore the matching database and document backup into the previous revision's new project before switching the test tunnel. Keep the failed candidate's volumes for diagnosis. Do not run a volume-removal command against the staging project during rollback.
