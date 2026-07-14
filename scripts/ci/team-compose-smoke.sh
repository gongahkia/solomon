#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
project="shibahama-team-smoke-$$"
compose_file="$ROOT/docker/compose.yml"
env_file="$tmpdir/runtime.env"
tls_dir="$tmpdir/oidc-tls"
realm_file="$tmpdir/shibahama-realm.json"
namespace="team-compose"
bootstrap_secret="$(openssl rand -hex 32)"
recovery_secret="$(openssl rand -hex 32)"
keycloak_admin_password="$(openssl rand -hex 32)"
keycloak_database_password="$(openssl rand -hex 32)"
oidc_password="$(openssl rand -hex 32)"
oidc_username="compose-smoke"
curl_image="curlimages/curl:8.18.0@sha256:d94d07ba9e7d6de898b6d96c1a072f6f8266c687af78a74f380087a0addf5d17"

compose() {
  docker compose --project-name "$project" --env-file "$env_file" -f "$compose_file" "$@"
}

curl_in_network() {
  docker run --rm \
    --network "${project}_default" \
    --volume "$tls_dir/ca.crt:/tls/ca.crt:ro" \
    "$curl_image" --cacert /tls/ca.crt "$@"
}

cleanup() {
  status="$?"
  if [[ "$status" -ne 0 ]]; then
    compose ps >&2 || true
    compose logs >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$tmpdir"
  exit "$status"
}
trap cleanup EXIT

install -d -m 0700 "$tls_dir"
openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 7 \
  -addext 'basicConstraints=critical,CA:TRUE' \
  -keyout "$tls_dir/ca.key" \
  -out "$tls_dir/ca.crt" \
  -subj '/CN=shibahama-compose-smoke-ca'
openssl req -newkey rsa:2048 -nodes \
  -keyout "$tls_dir/server.key" \
  -out "$tls_dir/server.csr" \
  -subj '/CN=keycloak'
printf 'subjectAltName=DNS:keycloak\nextendedKeyUsage=serverAuth\n' >"$tls_dir/server.ext"
openssl x509 -req -sha256 -days 7 \
  -in "$tls_dir/server.csr" \
  -CA "$tls_dir/ca.crt" \
  -CAkey "$tls_dir/ca.key" \
  -CAcreateserial \
  -out "$tls_dir/server.crt" \
  -extfile "$tls_dir/server.ext"
python3 - "$ROOT/docker/keycloak/shibahama-realm.json" "$realm_file" "$oidc_username" "$oidc_password" <<'PY'
import json
import pathlib
import sys

realm = json.loads(pathlib.Path(sys.argv[1]).read_text())
realm["users"] = [{
    "username": sys.argv[3],
    "enabled": True,
    "credentials": [{"type": "password", "value": sys.argv[4], "temporary": False}],
}]
pathlib.Path(sys.argv[2]).write_text(json.dumps(realm))
PY

{
  printf 'KEYCLOAK_ADMIN_USERNAME=admin\n'
  printf 'KEYCLOAK_ADMIN_PASSWORD=%s\n' "$keycloak_admin_password"
  printf 'KEYCLOAK_DATABASE_PASSWORD=%s\n' "$keycloak_database_password"
  printf 'KEYCLOAK_REALM_IMPORT_FILE=%s\n' "$realm_file"
  printf 'OIDC_TLS_DIR=%s\n' "$tls_dir"
  printf 'SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET=%s\n' "$bootstrap_secret"
  printf 'SHIBAHAMA_ADMIN_RECOVERY_SECRET=%s\n' "$recovery_secret"
  printf 'SHIBAHAMA_DIMENSIONS=2\n'
  printf 'SHIBAHAMA_ENCRYPTION_KEY=%s\n' "$(openssl rand -hex 32)"
  printf 'SHIBAHAMA_NAMESPACE=%s\n' "$namespace"
  printf 'SHIBAHAMA_PORT=0\n'
} >"$env_file"

compose up --build --detach --wait --wait-timeout 180

token_json="$(curl_in_network -sS -X POST \
  --data-urlencode client_id=shibahama \
  --data-urlencode grant_type=password \
  --data-urlencode "username=$oidc_username" \
  --data-urlencode "password=$oidc_password" \
  https://keycloak:8443/realms/shibahama/protocol/openid-connect/token)"
access_token="$(python3 -c 'import json,sys
record = json.load(sys.stdin)
token = record.get("access_token")
if not isinstance(token, str) or not token:
    raise SystemExit(
        f"OIDC password grant failed: {record.get('error', 'unknown error')} "
        f"{record.get('error_description', '')}"
    )
print(token)' <<<"$token_json")"

bootstrap="$(curl_in_network -fsS -X POST \
  -H "Authorization: Bearer $access_token" \
  -H "x-shibahama-bootstrap-secret: $bootstrap_secret" \
  -H "x-shibahama-namespace: $namespace" \
  -H 'x-shibahama-scope-visibility: repository' \
  http://shibahama:8765/admin/bootstrap)"
python3 -c 'import json,sys
assert json.loads(sys.argv[1]) == {"initialized": True}' "$bootstrap"

ready="$(curl_in_network -fsS \
  -H "Authorization: Bearer $access_token" \
  -H "x-shibahama-namespace: $namespace" \
  -H 'x-shibahama-scope-visibility: repository' \
  http://shibahama:8765/readyz)"
python3 -c 'import json,sys
record = json.loads(sys.argv[1])
assert record["status"] == "ready"
assert record["namespace"] == "team-compose"' "$ready"

mcp="$(curl_in_network -fsS -X POST \
  -H 'accept: application/json, text/event-stream' \
  -H "Authorization: Bearer $access_token" \
  -H 'content-type: application/json' \
  -H "x-shibahama-namespace: $namespace" \
  -H 'x-shibahama-scope-visibility: repository' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"team-compose-smoke","version":"1"}}}' \
  http://shibahama:8765/mcp)"
python3 -c 'import json,sys
record = json.loads(sys.argv[1])
assert record["jsonrpc"] == "2.0"
assert record["result"]["protocolVersion"] == "2025-11-25"' "$mcp"

printf 'team compose smoke passed\n'
