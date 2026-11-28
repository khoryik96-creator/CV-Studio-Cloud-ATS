#!/bin/sh
# Disposable CI only. No external egress, no worker dispatch, no live data.
set -eu
test "${GITHUB_ACTIONS:-}" = true
test "${RUNNER_OS:-}" = Linux
cd "$(dirname "$0")"
project="cvcloud-workspace-smoke-$(python3 -c 'import secrets; print(secrets.token_hex(8))')"
test -z "$(docker container ls -aq --filter "label=com.docker.compose.project=$project")"
for kind in network volume; do
    test -z "$(docker "$kind" ls -q --filter "label=com.docker.compose.project=$project")"
done
secret_dir=$(mktemp -d)
umask 077
export CVCLOUD_PUBLIC_ORIGIN=https://cvstudio.hyplug.co
export CVCLOUD_INGRESS_SUBNET=172.29.68.0/24
export CVCLOUD_TRUSTED_PROXY_IP=172.29.68.10
export CVCLOUD_LIVE_AI=disabled
for role in BOOTSTRAP SCHEMA AUTH DOCUMENT PROVIDER WORKER PROVIDER_READER SCHEDULER ADMIN; do
    file="$secret_dir/$role"
    python3 -c 'import secrets; print(secrets.token_hex(32))' > "$file"
    chmod 0444 "$file"
    export "CVCLOUD_${role}_SECRET_PATH=$file"
done
export CVCLOUD_KEYRING_SECRET_PATH="$secret_dir/keyring"
export CVCLOUD_MODEL_CATALOGUE_PATH="$secret_dir/catalogue"
python3 -c 'import json,secrets; print(json.dumps({"active_version":"ci","keys":{"ci":secrets.token_hex(32)}}))' > "$CVCLOUD_KEYRING_SECRET_PATH"
printf '%s\n' '[{"provider":"deepseek","model":"fictional-model","input_rate":100,"output_rate":200,"max_input_tokens":4096,"max_output_tokens":1024}]' > "$CVCLOUD_MODEL_CATALOGUE_PATH"
chmod 0444 "$CVCLOUD_KEYRING_SECRET_PATH" "$CVCLOUD_MODEL_CATALOGUE_PATH"
cat > "$secret_dir/probe.yaml" <<'YAML'
services:
  probe:
    image: cvcloud-online-workspace:local
    profiles: [test]
    networks:
      ingress:
        ipv4_address: 172.29.68.10
YAML
compose() { docker compose -p "$project" -f compose.online-workspace.yaml -f "$secret_dir/probe.yaml" "$@"; }
cleanup() {
    result=$?
    if [ "$result" -ne 0 ]; then
        # This script runs only on disposable CI with synthetic credentials.
        compose ps -a || true
        compose logs --no-color --tail=80 initialize migrate grant-install admin-install web || true
    fi
    compose down --remove-orphans --volumes >/dev/null 2>&1 || true
    rm -rf "$secret_dir"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
compose config --quiet
compose build web
compose up --no-build -d --wait --wait-timeout 240 web
test -z "$(docker container ls -aq --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=worker")"
for service in web online-db; do
    id=$(compose ps -q "$service")
    test -n "$id"
    docker inspect --format '{{json .HostConfig.PortBindings}}' "$id" | python3 -c 'import json,sys; assert not json.load(sys.stdin)'
done
compose exec -T web python -c 'from pathlib import Path; p=Path("/run/secrets"); assert all(not (p/f).exists() for f in ("schema_password","bootstrap_password","worker_password","provider_reader_password","scheduler_password")); assert Path("/srv/cvcloud/data").stat().st_mode & 0o777 == 0o700'
compose run --rm --no-deps -T --entrypoint python owner -c 'from cloud.deploy.online_owner import provision_owner,operator_connection; provision_owner(operator_connection,tenant="fictional",email="owner@example.test",password="synthetic-owner-ci-only-123")'
compose run --rm --no-deps -T --entrypoint python probe -c '
import json,http.client
def req(method,path,headers,body=None):
    c=http.client.HTTPConnection("web",8000,timeout=15)
    try:
        c.request(method,path,body=body,headers=headers)
        r=c.getresponse()
        return r.status,r.getheader("Set-Cookie"),r.read()
    finally:
        c.close()
origin="https://cvstudio.hyplug.co"
headers={"Host":"cvstudio.hyplug.co","Origin":origin,"X-Forwarded-For":"192.0.2.1","X-Forwarded-Proto":"https","Content-Type":"application/json"}
assert req("GET","/readyz",headers)[0]==503
status,_,page=req("GET","/cloud-ui",headers)
assert status==200 and b"Online workspace candidate" in page
status,cookie,_=req("POST","/api/auth/login",headers,json.dumps({"tenant":"fictional","email":"owner@example.test","password":"synthetic-owner-ci-only-123"}))
assert status==200 and "Secure" in cookie and "HttpOnly" in cookie
status,_,body=req("GET","/api/auth/me",dict(headers,Cookie=cookie.split(";")[0]))
assert status==200 and json.loads(body)["role"]=="owner"
headers=dict(headers,Cookie=cookie.split(";")[0],**{"X-CSRF-Token":json.loads(body)["csrf"],"Content-Type":"text/plain"})
status,_,body=req("POST","/api/documents",headers,b"Fictional workspace candidate")
assert status==201 and json.loads(body)["document_id"]
status,_,body=req("GET","/api/documents",headers)
assert status==200 and len(json.loads(body)["items"])==1
status,_,body=req("GET","/api/admin/accounts",headers)
assert status==200 and len(json.loads(body)["items"])==1
status,_,body=req("GET","/api/admin/ai-usage",headers)
assert status==200 and json.loads(body)=={"configured":False}
'
echo "Internal online workspace startup and authenticated UI passed. Live worker remains disabled."
