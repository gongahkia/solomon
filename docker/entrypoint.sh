#!/bin/sh
# SPDX-License-Identifier: MIT

set -eu
umask 077

fail() {
  echo "shibahama container configuration error: $*" >&2
  exit 64
}

require_nonempty() {
  value="$1"
  name="$2"
  [ -n "$value" ] || fail "$name is required"
}

require_positive_integer() {
  value="$1"
  name="$2"
  case "$value" in
    ''|*[!0-9]*) fail "$name must be a positive integer" ;;
  esac
  [ "$value" -gt 0 ] || fail "$name must be a positive integer"
}

require_boolean() {
  value="$1"
  name="$2"
  case "$value" in
    true|false) ;;
    *) fail "$name must be true or false" ;;
  esac
}

for name in $(env | sed -n 's/^\(SHIBAHAMA_[^=]*\)=.*/\1/p'); do
  case "$name" in
    SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET|SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS|SHIBAHAMA_ADMIN_RECOVERY_SECRET|SHIBAHAMA_API_KEY|SHIBAHAMA_BIND|SHIBAHAMA_CORS_ALLOW_CREDENTIALS|SHIBAHAMA_CORS_HEADERS|SHIBAHAMA_CORS_METHODS|SHIBAHAMA_CORS_ORIGINS|SHIBAHAMA_DATA_PATH|SHIBAHAMA_DIMENSIONS|SHIBAHAMA_ENCRYPTION_KEY|SHIBAHAMA_ENCRYPTION_KEY_ID|SHIBAHAMA_NAMESPACE|SHIBAHAMA_OIDC_AUDIENCE|SHIBAHAMA_OIDC_ISSUER|SHIBAHAMA_OIDC_PRINCIPAL_CLAIM|SHIBAHAMA_RATE_LIMIT_BURST|SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW|SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS|SHIBAHAMA_RBAC_ENFORCE|SHIBAHAMA_RBAC_ERASURE_MIN_ROLE|SHIBAHAMA_RBAC_PROMOTION_MIN_ROLE) ;;
    *) fail "$name is not supported by this image" ;;
  esac
done

[ "$#" -eq 0 ] || fail "arguments are not accepted; use documented SHIBAHAMA_* configuration"

data_path="${SHIBAHAMA_DATA_PATH:-/var/lib/shibahama/shibahama.redb}"
dimensions="${SHIBAHAMA_DIMENSIONS:-}"
bind="${SHIBAHAMA_BIND:-0.0.0.0:8765}"
namespace="${SHIBAHAMA_NAMESPACE:-default}"
api_key="${SHIBAHAMA_API_KEY:-}"
encryption_key="${SHIBAHAMA_ENCRYPTION_KEY:-}"
encryption_key_id="${SHIBAHAMA_ENCRYPTION_KEY_ID:-service-local}"
oidc_issuer="${SHIBAHAMA_OIDC_ISSUER:-}"
oidc_audience="${SHIBAHAMA_OIDC_AUDIENCE:-}"
oidc_principal_claim="${SHIBAHAMA_OIDC_PRINCIPAL_CLAIM:-}"
rbac_enforce="${SHIBAHAMA_RBAC_ENFORCE:-true}"

case "$data_path" in
  /*) ;;
  *) fail "SHIBAHAMA_DATA_PATH must be absolute" ;;
esac
require_positive_integer "$dimensions" "SHIBAHAMA_DIMENSIONS"
require_nonempty "$encryption_key" "SHIBAHAMA_ENCRYPTION_KEY"
[ "${#encryption_key}" -eq 64 ] || fail "SHIBAHAMA_ENCRYPTION_KEY must contain 64 hexadecimal characters"
case "$encryption_key" in
  *[!0123456789abcdefABCDEF]*) fail "SHIBAHAMA_ENCRYPTION_KEY must contain 64 hexadecimal characters" ;;
esac
require_boolean "$rbac_enforce" "SHIBAHAMA_RBAC_ENFORCE"

if [ -z "$api_key" ] && { [ -z "$oidc_issuer" ] || [ -z "$oidc_audience" ]; }; then
  fail "SHIBAHAMA_API_KEY or both SHIBAHAMA_OIDC_ISSUER and SHIBAHAMA_OIDC_AUDIENCE are required"
fi
if [ -n "$oidc_issuer" ] && [ -z "$oidc_audience" ]; then
  fail "SHIBAHAMA_OIDC_AUDIENCE is required with SHIBAHAMA_OIDC_ISSUER"
fi
if [ -z "$oidc_issuer" ] && [ -n "$oidc_audience" ]; then
  fail "SHIBAHAMA_OIDC_ISSUER is required with SHIBAHAMA_OIDC_AUDIENCE"
fi

for pair in \
  "${SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS:-}:SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS" \
  "${SHIBAHAMA_RATE_LIMIT_BURST:-}:SHIBAHAMA_RATE_LIMIT_BURST" \
  "${SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW:-}:SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW" \
  "${SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS:-}:SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS"; do
  value="${pair%%:*}"
  name="${pair#*:}"
  [ -z "$value" ] || require_positive_integer "$value" "$name"
done

mkdir -p "$(dirname "$data_path")"

set -- /usr/local/bin/shibahama serve \
  --path "$data_path" \
  --dimensions "$dimensions" \
  --bind "$bind" \
  --namespace "$namespace" \
  --encryption-key "$encryption_key" \
  --encryption-key-id "$encryption_key_id"

[ -z "$api_key" ] || set -- "$@" --api-key "$api_key"
[ -z "$oidc_issuer" ] || set -- "$@" --oidc-issuer "$oidc_issuer" --oidc-audience "$oidc_audience"
[ -z "$oidc_principal_claim" ] || set -- "$@" --oidc-principal-claim "$oidc_principal_claim"
[ "$rbac_enforce" = false ] || set -- "$@" --rbac-enforce

[ -z "${SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET:-}" ] || set -- "$@" --admin-bootstrap-secret "$SHIBAHAMA_ADMIN_BOOTSTRAP_SECRET"
[ -z "${SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS:-}" ] || set -- "$@" --admin-bootstrap-ttl-seconds "$SHIBAHAMA_ADMIN_BOOTSTRAP_TTL_SECONDS"
[ -z "${SHIBAHAMA_ADMIN_RECOVERY_SECRET:-}" ] || set -- "$@" --admin-recovery-secret "$SHIBAHAMA_ADMIN_RECOVERY_SECRET"
[ -z "${SHIBAHAMA_CORS_HEADERS:-}" ] || set -- "$@" --cors-header "$SHIBAHAMA_CORS_HEADERS"
[ -z "${SHIBAHAMA_CORS_METHODS:-}" ] || set -- "$@" --cors-method "$SHIBAHAMA_CORS_METHODS"
[ -z "${SHIBAHAMA_CORS_ORIGINS:-}" ] || set -- "$@" --cors-origin "$SHIBAHAMA_CORS_ORIGINS"
[ -z "${SHIBAHAMA_RATE_LIMIT_BURST:-}" ] || set -- "$@" --rate-limit-burst "$SHIBAHAMA_RATE_LIMIT_BURST"
[ -z "${SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW:-}" ] || set -- "$@" --rate-limit-requests-per-window "$SHIBAHAMA_RATE_LIMIT_REQUESTS_PER_WINDOW"
[ -z "${SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS:-}" ] || set -- "$@" --rate-limit-window-seconds "$SHIBAHAMA_RATE_LIMIT_WINDOW_SECONDS"
[ -z "${SHIBAHAMA_RBAC_ERASURE_MIN_ROLE:-}" ] || set -- "$@" --rbac-erasure-min-role "$SHIBAHAMA_RBAC_ERASURE_MIN_ROLE"
[ -z "${SHIBAHAMA_RBAC_PROMOTION_MIN_ROLE:-}" ] || set -- "$@" --rbac-promotion-min-role "$SHIBAHAMA_RBAC_PROMOTION_MIN_ROLE"

cors_allow_credentials="${SHIBAHAMA_CORS_ALLOW_CREDENTIALS:-false}"
require_boolean "$cors_allow_credentials" "SHIBAHAMA_CORS_ALLOW_CREDENTIALS"
[ "$cors_allow_credentials" = false ] || set -- "$@" --cors-allow-credentials

exec /usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin "$@"
