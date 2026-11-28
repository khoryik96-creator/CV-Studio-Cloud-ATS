#!/bin/sh
set -eu
cd "$(dirname "$0")"
project="cvcloud-fixture-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
compose() { docker compose -p "$project" -f compose.fixture.yaml "$@"; }
if [ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$project")" ]; then
    echo "Unexpected existing project" >&2; exit 1
fi
cleanup() { compose down --remove-orphans --volumes; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose up --build --abort-on-container-exit --exit-code-from check
