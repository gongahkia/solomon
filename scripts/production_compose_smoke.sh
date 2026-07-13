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
