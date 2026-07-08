#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
zig="${ZIG:-zig}"

"$zig" test "$root/src/plugin/capability.zig" --test-filter "symlink pointing outside scope is denied"
"$zig" test "$root/src/plugin/capability.zig" --test-filter "dot-dot traversal is denied"
"$zig" test "$root/src/plugin/capability.zig" --test-filter "nested symlink chain outside scope is denied"
"$zig" test "$root/src/plugin/capability.zig" --test-filter "symlink to allowed file inside scope is permitted"
"$zig" test "$root/src/plugin/capability.zig" --test-filter "hostile plugin traversal requests are denied without side effects"

printf 'plugin capability traversal: ok\n'
