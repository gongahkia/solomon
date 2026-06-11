#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
RUSTFLAGS="-Dwarnings" cargo test --workspace --all-targets --all-features
