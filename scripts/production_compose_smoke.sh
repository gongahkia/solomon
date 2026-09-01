#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

set -eu

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required to run the production Compose smoke test" >&2
    exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
    echo "curl is required to run the production Compose smoke test" >&2
    exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
project="solomon-smoke-$$"
secrets_dir="$(mktemp -d)"

cleanup() {
    status=$?
    if [ "$status" -ne 0 ]; then
        docker compose --project-name "$project" -f "$root/docker-compose.production.yml" --profile production logs || true
    fi
    docker compose --project-name "$project" -f "$root/docker-compose.production.yml" --profile production down --volumes --remove-orphans || true
    rm -rf "$secrets_dir"
    exit "$status"
}
trap cleanup EXIT HUP INT TERM

umask 077
printf '%s\n' 'test-server-api-key' > "$secrets_dir/server_api_key"
printf '%s\n' 'test-console-bearer-token' > "$secrets_dir/console_bearer_token"
printf '%s\n' 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=' > "$secrets_dir/content_encryption_key"
printf '%s\n' 'test-postgres-password' > "$secrets_dir/postgres_password"

export SOLOMON_SECRETS_DIR="$secrets_dir"
export SOLOMON_CONTENT_ENCRYPTION_KEY_REF='kms://solomon/test'
export SOLOMON_API_BIND='127.0.0.1:0'
export SOLOMON_CONSOLE_BIND='127.0.0.1:0'

cd "$root"
docker compose --project-name "$project" -f docker-compose.production.yml --profile production up --build --detach --wait --wait-timeout 240

api_endpoint="$(docker compose --project-name "$project" -f docker-compose.production.yml port api 8140)"
console_endpoint="$(docker compose --project-name "$project" -f docker-compose.production.yml port console 8150)"
curl --fail --silent --show-error "http://$api_endpoint/health" >/dev/null
curl --fail --silent --show-error "http://$console_endpoint/health" >/dev/null
curl --fail --silent --show-error \
    -H 'Authorization: Bearer test-console-bearer-token' \
    "http://$console_endpoint/console/verification" >/dev/null
curl --fail --silent --show-error \
    -H 'Authorization: Bearer test-console-bearer-token' \
    "http://$console_endpoint/console/sources" >/dev/null
curl --fail --silent --show-error \
    -H 'x-api-key: test-server-api-key' \
    -H 'Content-Type: application/json' \
    -X POST "http://$api_endpoint/tenants" \
    --data '{"tenant_id":"compose-smoke","display_name":"Compose smoke"}' >/dev/null
api_response="$(curl --fail --silent --show-error \
    -H 'x-api-key: test-server-api-key' \
    -H 'x-tenant-id: compose-smoke' \
    -H 'Content-Type: application/json' \
    -X POST "http://$api_endpoint/ingest" \
    --data '{"content":"Compose rehearsal position: structure X remains governed by Regulation R section 12.","kind":"house-view","source_kind":"partner","source_ref":"compose-rehearsal","author":"Compose Rehearsal"}')"
api_item_id="$(printf '%s' "$api_response" | python -c '
import json
import sys
value = json.load(sys.stdin).get("id")
if not isinstance(value, str) or not value:
    raise SystemExit("authenticated API ingest did not return an item id")
print(value)
')"
curl --fail --silent --show-error \
    -H 'x-api-key: test-server-api-key' \
    -H 'x-tenant-id: compose-smoke' \
    "http://$api_endpoint/currency/$api_item_id" > "$secrets_dir/api-currency.json"
# Run the in-profile CLI through the production entrypoint so file-backed
# secrets are loaded before it drops to the unprivileged service identity.
docker compose --project-name "$project" -f docker-compose.production.yml --profile production \
    exec -T --user root api /usr/local/bin/solomon-entrypoint solomon deployment preflight \
    --require-initialized --format json > "$secrets_dir/cli-preflight.json"
python - "$secrets_dir/api-currency.json" "$secrets_dir/cli-preflight.json" <<'PY'
import json
import sys

currency = json.load(open(sys.argv[1], encoding="utf-8"))
preflight = json.load(open(sys.argv[2], encoding="utf-8"))
if not isinstance(currency.get("currency_state"), str):
    raise SystemExit("authenticated API read did not return currency state")
if preflight.get("ready") is not True:
    raise SystemExit("in-profile CLI preflight was not ready")
PY
