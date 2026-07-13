#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

expected_toolchain="$(sed -n 's/^channel = "\(.*\)"$/\1/p' rust-toolchain.toml)"
actual_toolchain="$(rustc --version | awk '{print $2}')"

if [[ "$actual_toolchain" != "$expected_toolchain" ]]; then
  echo "expected Rust $expected_toolchain, found $actual_toolchain" >&2
  exit 1
fi

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
RUSTFLAGS="-Dwarnings" cargo test --workspace --all-targets --all-features
