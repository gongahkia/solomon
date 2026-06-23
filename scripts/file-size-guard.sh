#!/usr/bin/env bash
# Fail if any tracked Zig file under src/daemon/ has more than $LIMIT lines.
# Rationale: daemon hot-path code under Zig pre-1.0 churn risk concentrates
# in oversized files. The threshold matches north-star §16 mitigation ("keep
# CLI modules small enough that a language break is a day of work, not a month").
set -euo pipefail

LIMIT=${SHISA_DAEMON_FILE_LIMIT:-3000}
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

over_limit=()
while IFS= read -r path; do
  lines=$(wc -l < "$ROOT/$path" | tr -d ' ')
  if (( lines > LIMIT )); then
    over_limit+=("$path:$lines")
  fi
done < <(cd "$ROOT" && git ls-files 'src/daemon/*.zig' 'src/daemon/**/*.zig')

if (( ${#over_limit[@]} > 0 )); then
  printf 'file-size-guard: %d file(s) over %d lines:\n' "${#over_limit[@]}" "$LIMIT" >&2
  for entry in "${over_limit[@]}"; do
    printf '  %s\n' "$entry" >&2
  done
  printf '\n' >&2
  printf 'Split before adding more. See north-star §16 (Zig pre-1.0 churn mitigation).\n' >&2
  exit 1
fi

printf 'file-size-guard: all src/daemon/*.zig under %d lines.\n' "$LIMIT"
