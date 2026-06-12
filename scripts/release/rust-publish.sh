#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ "${SHIBAHAMA_ALLOW_DIRTY:-0}" != "1" ]] && [[ -n "$(git -C "$repo_root" status --short)" ]]; then
  printf 'release checks require a clean worktree; set SHIBAHAMA_ALLOW_DIRTY=1 for local draft checks\n' >&2
  exit 1
fi

(
  cd "$repo_root"
  cargo package -p shibahama-core --allow-dirty
  cargo publish -p shibahama-core --dry-run --allow-dirty
)

if [[ "${SHIBAHAMA_PUBLISH:-0}" != "1" ]]; then
  printf 'packaged shibahama-core and dry-ran shibahama-core publish\n'
  printf 'shibahama-cli package verification requires shibahama-core 0.1.0 to exist in the crates.io index\n'
  printf 'set SHIBAHAMA_PUBLISH=1 with Cargo registry auth to upload\n'
  exit 0
fi

if [[ -z "${CARGO_REGISTRY_TOKEN:-}" && ! -f "$HOME/.cargo/credentials.toml" ]]; then
  printf 'Cargo registry auth is required to publish crates\n' >&2
  exit 1
fi

(
  cd "$repo_root"
  cargo publish -p shibahama-core
  printf 'wait for shibahama-core 0.1.0 to appear in the crates.io index before publishing shibahama-cli\n'
  cargo publish -p shibahama-cli
)
