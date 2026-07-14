#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
state_dir="${SHIBAHAMA_TEAM_STATE_DIR:-$ROOT/.shibahama/team-compose}"
env_file="$state_dir/runtime.env"
compose_file="$ROOT/docker/compose.yml"

install -d -m 0700 "$state_dir"
if [[ ! -f "$env_file" ]]; then
  umask 077
  {
    printf 'KEYCLOAK_ADMIN_USERNAME=admin\n'
    printf 'KEYCLOAK_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'KEYCLOAK_DATABASE_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_ADMIN_RECOVERY_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_DIMENSIONS=2\n'
    printf 'SHIBAHAMA_ENCRYPTION_KEY=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_NAMESPACE=team-compose\n'
    printf 'SHIBAHAMA_PORT=8765\n'
  } >"$env_file"
fi

docker compose --env-file "$env_file" -f "$compose_file" up --build --detach --wait "$@"
printf 'Shibahama team environment is ready at http://127.0.0.1:8765\n'
printf 'Runtime secrets are stored only in %s\n' "$env_file"
