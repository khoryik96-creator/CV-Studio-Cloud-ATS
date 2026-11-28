#!/bin/sh
# Explicit disposable project; refuses to use any pre-existing Compose project.
set -eu
cd "$(dirname "$0")"
project="cvcloud-smoke-$$"
export CVCLOUD_HEALTH_PORT="${CVCLOUD_HEALTH_PORT:-18080}"
case "$CVCLOUD_HEALTH_PORT" in ''|*[!0-9]*) echo "Invalid port" >&2; exit 1;; esac
compose() { docker compose -p "$project" -f compose.yaml "$@"; }
cleanup() { compose down --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose up --build -d --wait --wait-timeout 90
cid="$(compose ps -q health)"
test -n "$cid"
test "$(docker inspect --format '{{.Config.User}}' "$cid")" = "10001:10001"
test "$(docker inspect --format '{{.HostConfig.ReadonlyRootfs}}' "$cid")" = "true"
test "$(docker inspect --format '{{(index (index .HostConfig.PortBindings "8000/tcp") 0).HostIp}}' "$cid")" = "127.0.0.1"
base="http://127.0.0.1:$CVCLOUD_HEALTH_PORT"
test "$(curl --noproxy '*' --max-time 5 -sS -o /dev/null -w '%{http_code}' "$base/healthz")" = 200
test "$(curl --noproxy '*' --max-time 5 -sS -o /dev/null -w '%{http_code}' "$base/readyz")" = 503
for path in / /cloud-ui /activate /api/auth/login /parse /generate-docx /jobadder /apollo /ocr; do
    for method in GET POST; do
        test "$(curl --noproxy '*' --max-time 5 -sS -X "$method" -o /dev/null -w '%{http_code}' "$base$path")" = 404
    done
done
echo "Health-only container smoke passed; production readiness remains disabled."
