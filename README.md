# stonks-cli

`stonks-cli` is a paper-first research and carry-validation CLI for SG-legal crypto venues. Hyperliquid is the first supported venue; funding/basis carry is the only live-candidate path.

## Status

- Wallet analysis, ingestion, and paper replay are research-only.
- Carry remains paper-first. Tiny live operation is blocked on the 30-day carry paper gate, legal review, custody review, and explicit preflight.
- Equity analysis, prediction-market execution, and sportsbook execution are out of scope.

## Commands

```console
$ stonks-cli --help
$ stonks-cli                         # interactive local status home
$ stonks-cli onboard                 # guided paper-first configuration
$ stonks-cli settings                # guided safe settings editor
$ stonks-cli home --json             # machine-readable local readiness
$ stonks-cli clean --dry-run         # inspect removable cache/state paths
$ stonks-cli uninstall --dry-run     # inspect app-data removal and package guidance
$ stonks-cli init-config
$ stonks-cli replay-ingest --fixture tests/fixtures/research/hyperliquid-ws.jsonl
$ stonks-cli rank-wallet --fixture tests/fixtures/research/wallet-attribution.jsonl
$ stonks-cli replay-paper --fixture tests/fixtures/research/paper-mirror.jsonl
$ stonks-cli scan-carry
$ stonks-cli run-carry-paper --asset BTC --asset ETH
$ stonks-cli preflight-carry-live
```

Old grouped command paths are intentionally unsupported.

## First run

Run `stonks-cli onboard` from an interactive terminal. It creates or updates local configuration, preserves a timestamped backup of an existing config, and can enable paper carry, crypto research, read-only Moomoo support, and operator-report settings. It never asks for secret values, enables execution, or arms live trading.

`stonks-cli` without a command shows the local readiness home in an interactive terminal; in scripts it prints compact help. Use `stonks-cli home --json` for automation.

`clean` removes only app-owned per-user cache and generated state after confirmation. `uninstall` also removes app-owned local config/data, then prints package-manager guidance; it does not remove the package itself. Neither command removes Linux carry-gate evidence or paths outside the managed per-user directories.

## Validation

- [Capture validation](docs/validation-gates.md) documents the historical Hyperliquid connector gate.
- [30-day carry paper gate](docs/carry-30d-paper-gate.md) is GitHub issue #14's active acceptance contract.
- [Carry venue policy](docs/carry-sg-venue-policy.md) and [tiny-live runbook](docs/carry-tiny-live-runbook.md) define the fail-closed live posture.

## Safety

No command authorizes trading. Polymarket, Kalshi, sportsbooks, Bybit, and circumvention-based execution are blocked for SG use. Outputs are not financial, legal, tax, or investment advice.
