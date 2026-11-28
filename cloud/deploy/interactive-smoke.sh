#!/bin/sh
set -eu
cd "$(dirname "$0")"
mode=${1:-}
if [ "$#" -gt 1 ] || { [ -n "$mode" ] && [ "$mode" != "--verify-restore" ]; }; then
    echo "Usage: $0 [--verify-restore]" >&2
    exit 2
fi
project="cvcloud-interactive-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
compose() { docker compose -p "$project" -f compose.interactive.yaml "$@"; }
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]; then
    echo "Unexpected existing project" >&2; exit 1
fi
backup=$(mktemp -d)
cert="$backup/cvcloud.crt"
port=${CVCLOUD_FIXTURE_PORT:-443}
cleanup() {
    rm -rf "$backup"
    compose down --remove-orphans --volumes
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose up --build -d --wait --wait-timeout 180
compose exec -T web cat /tmp/cvcloud.crt > "$cert"
curl --fail --silent --show-error --max-time 10 --noproxy '*' \
    --resolve "cv.example.test:$port:127.0.0.1" --header 'Host: cv.example.test' \
    --cacert "$cert" "https://cv.example.test:$port/staging-readyz" > /dev/null
job_id=$(compose exec -T web python -m cloud.deploy.interactive_check)
compose stop worker
compose exec -T web python -m cloud.deploy.interactive_check not-ready
compose down
compose up -d --wait --wait-timeout 180
compose exec -T web python -m cloud.deploy.interactive_check persistence "$job_id"


if [ "$mode" = "--verify-restore" ]; then
    # Capture consistent database metadata and private objects while idle.
    compose stop web worker
    compose exec -T db pg_dump -U postgres -d cvcloud_test --format=custom > "$backup/database.dump"
    compose run --no-deps --rm -T --entrypoint tar web \
        -C /srv/cvcloud/data --exclude=.fixture-worker-heartbeat -czf - . > "$backup/documents.tar.gz"

    # This project was generated above for this test. Start with empty volumes.
    compose down --volumes
    compose up -d --wait --wait-timeout 90 db
    compose exec -T db psql -X -v ON_ERROR_STOP=1 -U postgres -d cvcloud_test <<'SQL'
CREATE ROLE cvcloud_runtime LOGIN PASSWORD 'synthetic-runtime-only' NOSUPERUSER NOBYPASSRLS;
SQL
    compose exec -T db pg_restore -U postgres -d cvcloud_test --single-transaction --exit-on-error --no-owner \
        < "$backup/database.dump"
    compose run --no-deps --rm -T --entrypoint tar web \
        --no-same-owner -C /srv/cvcloud/data -xzf - < "$backup/documents.tar.gz"
    compose up -d --wait --wait-timeout 180
    compose exec -T web python -m cloud.deploy.interactive_check persistence "$job_id"
    echo "Synthetic PostgreSQL and private documents restored onto empty volumes"
fi
