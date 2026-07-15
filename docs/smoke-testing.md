# Synthetic smoke testing

Synthetic data proves only wiring, parsing, and paper-only safety. It is not live-capture, performance, or carry-gate evidence.

## One command

```console
$ uv run python scripts/smoke_synthetic.py
```

The final JSON identifies an isolated `smoke_root` and `smoke-provenance.json`. The runner redirects config, state, cache, MCP confirmations/jobs, and artifacts under that root; it does not use network data or the normal app directories.

Set `STONKS_CLI_SMOKE_ROOT` to retain a chosen result directory:

```console
$ export STONKS_CLI_SMOKE_ROOT="$PWD/.tmp/smoke"
$ uv run python scripts/smoke_synthetic.py
$ jq '.synthetic, .not_validation_evidence, .cli.home.safety, .mcp' "$STONKS_CLI_SMOKE_ROOT/smoke-provenance.json"
```

Expected invariants: `synthetic: true`, `not_validation_evidence: true`, `live_execution: blocked`, valid config, three ranked wallets, two closed replay-paper trades, a paper-carry report/ledger, and a confirmed MCP fixture-ingest artifact.

## Manual CLI path

```console
$ export SMOKE_DIR="$(mktemp -d)"
$ export STONKS_CLI_HOME="$SMOKE_DIR/app"
$ export STONKS_CLI_CONFIG="$STONKS_CLI_HOME/config.json"
$ uv run stonks-cli init-config --path "$STONKS_CLI_CONFIG"
$ uv run stonks-cli home --json
$ uv run stonks-cli doctor --smoke
$ uv run stonks-cli replay-ingest --fixture tests/fixtures/research/hyperliquid-ws.jsonl --out "$SMOKE_DIR/normalized.jsonl"
$ uv run stonks-cli rank-wallet --fixture tests/fixtures/research/wallet-attribution.jsonl
$ uv run stonks-cli replay-paper --fixture tests/fixtures/research/paper-mirror.jsonl --rankings-fixture tests/fixtures/research/wallet-attribution.jsonl
$ uv run stonks-cli alert-preview --event stale_data
```

`alert-preview` does not send Telegram or email. A configured alert sink without its environment credentials should report `configured; credentials missing` in `home --json`.

## MCP path

The one-command runner performs a real stdio MCP initialize/list-tools/call-tools flow, including one confirmation-gated fixture write. For client setup, use [MCP setup](mcp.md) with:

```console
$ export STONKS_CLI_HOME="$SMOKE_DIR/app"
$ export STONKS_CLI_MCP_ROOTS="$PWD:$SMOKE_DIR"
$ uv run stonks-mcp
```

Use read-only MCP tools (`status`, `doctor` with `smoke: true`, `carry_scan`, `research_rank_wallets`, `research_replay_paper`, `alert_preview`) directly. Every write requires `prepare_mutation` followed by one-time `confirm_mutation`.
