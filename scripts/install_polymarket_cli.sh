#!/usr/bin/env bash
set -euo pipefail

if command -v polymarket >/dev/null 2>&1; then
  echo "polymarket-cli already installed at: $(command -v polymarket)"
  polymarket --version || true
  exit 0
fi

if command -v brew >/dev/null 2>&1; then
  brew tap Polymarket/polymarket-cli https://github.com/Polymarket/polymarket-cli
  brew install polymarket
else
  curl -sSL https://raw.githubusercontent.com/Polymarket/polymarket-cli/main/install.sh | sh
fi

echo "installed polymarket-cli at: $(command -v polymarket)"
polymarket --version
