#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

(
  cd "$repo_root/bindings/node"
  npm ci --silent
  npm run build --silent
  npm test --silent
  npm pack --dry-run
)

if [[ "${SHIBAHAMA_PUBLISH:-0}" != "1" ]]; then
  printf 'built, tested, and dry-packed bindings/node\n'
  printf 'set SHIBAHAMA_PUBLISH=1 with npm auth or trusted publishing to upload\n'
  exit 0
fi

auth_value="${NODE_AUTH_TOKEN:-${NPM_TOKEN:-}}"
if [[ -n "$auth_value" ]]; then
  npmrc="$tmpdir/npmrc"
  printf '//registry.npmjs.org/:_authToken=%s\n' "$auth_value" > "$npmrc"
  export NPM_CONFIG_USERCONFIG="$npmrc"
fi

(
  cd "$repo_root/bindings/node"
  npm whoami >/dev/null
  npm publish --access public
)
