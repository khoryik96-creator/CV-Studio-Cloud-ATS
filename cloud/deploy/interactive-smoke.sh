#!/bin/sh
set -eu
cd "$(dirname "$0")"
project="cvcloud-interactive-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
compose() { docker compose -p "$project" -f compose.interactive.yaml "$@"; }
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]; then
    echo "Unexpected existing project" >&2; exit 1
fi
cert=$(mktemp)
cleanup() {
    rm -f "$cert"
    compose down --remove-orphans --volumes
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose up --build -d --wait --wait-timeout 180
compose exec -T web cat /tmp/cvcloud.crt > "$cert"
curl --fail --silent --show-error --max-time 10 --noproxy '*' \
    --resolve cv.example.test:443:127.0.0.1 --cacert "$cert" https://cv.example.test/healthz > /dev/null
job_id=$(compose exec -T web python -m cloud.deploy.interactive_check)
compose down
compose up -d --wait --wait-timeout 180
compose exec -T web python -m cloud.deploy.interactive_check persistence "$job_id"
