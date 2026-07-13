#!/bin/sh
# SPDX-License-Identifier: Apache-2.0

set -eu

if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required to validate the production Compose file" >&2
    exit 2
fi

root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
secrets_dir="$(mktemp -d)"
trap 'rm -rf "$secrets_dir"' EXIT HUP INT TERM
umask 077
printf '%s\n' 'test-server-api-key' > "$secrets_dir/server_api_key"
printf '%s\n' 'MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=' > "$secrets_dir/content_encryption_key"
printf '%s\n' 'test-postgres-password' > "$secrets_dir/postgres_password"

cd "$root"
SOLOMON_SECRETS_DIR="$secrets_dir" \
SOLOMON_CONTENT_ENCRYPTION_KEY_REF='kms://solomon/test' \
docker compose -f docker-compose.production.yml config --quiet
