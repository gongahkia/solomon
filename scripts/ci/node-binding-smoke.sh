#!/usr/bin/env bash
# SPDX-License-Identifier: MIT

set -euo pipefail

(
  cd bindings/node
  npm install --silent
  npm run build --silent
  npm test --silent
)
