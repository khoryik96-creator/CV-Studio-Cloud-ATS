#!/bin/sh
set -eu
cd "$(dirname "$0")"
project="cvcloud-interactive-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
compose() { docker compose -p "$project" -f compose.interactive.yaml "$@"; }
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]; then
    echo "Unexpected existing project" >&2; exit 1
fi
cleanup() { compose down --remove-orphans --volumes; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose up --build -d --wait --wait-timeout 180
compose exec -T web python -m cloud.deploy.interactive_check
