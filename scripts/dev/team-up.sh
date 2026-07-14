#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
state_dir="${SHIBAHAMA_TEAM_STATE_DIR:-$ROOT/.shibahama/team-compose}"
env_file="$state_dir/runtime.env"
tls_dir="$state_dir/oidc-tls"
compose_file="$ROOT/docker/compose.yml"

install -d -m 0700 "$state_dir"
install -d -m 0700 "$tls_dir"
if [[ ! -f "$tls_dir/ca.crt" || ! -f "$tls_dir/server.crt" || ! -f "$tls_dir/server.key" ]]; then
  umask 077
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 7 \
    -addext 'basicConstraints=critical,CA:TRUE' \
    -keyout "$tls_dir/ca.key" \
    -out "$tls_dir/ca.crt" \
    -subj '/CN=shibahama-local-oidc-ca'
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
fi
if [[ ! -f "$env_file" ]]; then
  umask 077
  {
    printf 'KEYCLOAK_ADMIN_USERNAME=admin\n'
    printf 'KEYCLOAK_ADMIN_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'KEYCLOAK_DATABASE_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'OIDC_TLS_DIR=%s\n' "$tls_dir"
    printf 'SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_ADMIN_RECOVERY_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_DIMENSIONS=2\n'
    printf 'SHIBAHAMA_ENCRYPTION_KEY=%s\n' "$(openssl rand -hex 32)"
    printf 'SHIBAHAMA_NAMESPACE=team-compose\n'
    printf 'SHIBAHAMA_PORT=8765\n'
  } >"$env_file"
fi
if ! grep -q '^OIDC_TLS_DIR=' "$env_file"; then
  printf 'OIDC_TLS_DIR=%s\n' "$tls_dir" >>"$env_file"
fi

docker compose --env-file "$env_file" -f "$compose_file" up --build --detach --wait "$@"
printf 'Shibahama team environment is ready at http://127.0.0.1:8765\n'
printf 'Runtime secrets are stored only in %s\n' "$env_file"
