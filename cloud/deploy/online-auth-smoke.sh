#!/bin/sh
# Destructive cleanup applies only to this randomly named disposable CI project.
set -eu
test "${GITHUB_ACTIONS:-}" = true
test "${RUNNER_OS:-}" = Linux
cd "$(dirname "$0")"
project="cvcloud-auth-smoke-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
test -z "$(docker container ls -aq --filter "label=com.docker.compose.project=$project")"
for kind in network volume; do
    test -z "$(docker "$kind" ls -q --filter "label=com.docker.compose.project=$project")"
done
secret_dir=$(mktemp -d)
export CVCLOUD_PUBLIC_ORIGIN=https://cvstudio.hyplug.co
export CVCLOUD_INGRESS_SUBNET=172.29.67.0/24
export CVCLOUD_TRUSTED_PROXY_IP=172.29.67.10
export CVCLOUD_BOOTSTRAP_SECRET_PATH="$secret_dir/bootstrap"
export CVCLOUD_SCHEMA_SECRET_PATH="$secret_dir/schema"
export CVCLOUD_AUTH_SECRET_PATH="$secret_dir/auth"
compose() { docker compose -p "$project" -f compose.online-auth.yaml -f "$secret_dir/probe.yaml" "$@"; }
cleanup() {
    compose down --remove-orphans --volumes >/dev/null 2>&1 || true
    rm -rf "$secret_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
umask 077
for file in "$CVCLOUD_BOOTSTRAP_SECRET_PATH" "$CVCLOUD_SCHEMA_SECRET_PATH" "$CVCLOUD_AUTH_SECRET_PATH"; do
    python3 -c 'import secrets; print(secrets.token_hex(32))' > "$file"
    chmod 0444 "$file"
done
cat > "$secret_dir/probe.yaml" <<'YAML'
services:
  probe:
    image: cvcloud-online-auth:local
    profiles: [test]
    networks:
      ingress:
        ipv4_address: 172.29.67.10
YAML
compose config --quiet
compose up --build -d --wait --wait-timeout 180 web
for service in web online-db; do
    id=$(compose ps -q "$service")
    test -n "$id"
    docker inspect --format '{{json .HostConfig.PortBindings}}' "$id" | python3 -c 'import json,sys; assert not json.load(sys.stdin)'
done
compose exec -T web python -c 'from pathlib import Path; assert Path("/run/secrets/auth_password").is_file(); assert not Path("/run/secrets/schema_password").exists(); assert not Path("/run/secrets/bootstrap_password").exists()'
compose run --rm --no-deps -T --entrypoint python owner -c 'from cloud.deploy.online_owner import provision_owner,operator_connection; provision_owner(operator_connection,tenant="fictional",email="owner@example.test",password="synthetic-owner-ci-only-123")'
probe() {
    compose run --rm --no-deps -T --entrypoint python probe -c '
import json, http.client
def req(method,path,headers,body=None):
    c=http.client.HTTPConnection("web",8000,timeout=10)
    try:
        c.request(method,path,body=body,headers=headers)
        r=c.getresponse()
        return r.status,r.getheader("Set-Cookie"),r.read()
    finally:
        c.close()
origin="https://cvstudio.hyplug.co"
headers={"Host":"cvstudio.hyplug.co","Origin":origin,"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https","Content-Type":"application/json"}
assert req("GET","/healthz",headers)[0]==200
assert req("GET","/readyz",headers)[0]==503
assert req("GET","/cloud-ui",headers)[0]==404
payload=json.dumps({"tenant":"fictional","email":"owner@example.test","password":"synthetic-owner-ci-only-123"})
status,cookie,_=req("POST","/api/auth/login",headers,payload)
assert status==200 and "Secure" in cookie and "HttpOnly" in cookie
status,_,body=req("GET","/api/auth/me",dict(headers,Cookie=cookie.split(";")[0]))
assert status==200 and json.loads(body)["role"]=="owner"
'
}
probe
# Reinitialize against the same marked schema without changing credentials/data.
compose run --rm --no-deps -T initialize
compose restart web
compose up -d --no-build --wait --wait-timeout 120 web
probe
echo "Isolated online auth Compose smoke passed; production remains disabled."
