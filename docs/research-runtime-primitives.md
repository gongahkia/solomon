# stonks-cli Runtime Primitives

Status: accepted on 2026-05-17.

The Phase 1 runtime keeps the existing scheduler, config, storage, plugin loader, journal discipline, and Rust hotpath, but new stonks-cli surfaces use venue-neutral models first. Hyperliquid is the first concrete venue.

## Venue-Neutral Interfaces

| Primitive | Module | Purpose |
| --- | --- | --- |
| `NormalizedTrade` | `stonks_cli.research.models` | Common decoded trade shape for Hyperliquid now and future SG-legal venues later. |
| `ExecutionIntent` | `stonks_cli.research.models` | Paper, dry-run, or live order intent before venue submission. |
| `AttributionMetrics` | `stonks_cli.research.models` | Wallet ranking metrics: expectancy, Sharpe, decay, survivorship-adjusted PnL, and funding-adjusted PnL. |
| `DecisionRecord` | `stonks_cli.research.models` | Journal and ledger record for signal-to-decision-to-outcome traceability. |
| `evaluate_execution_guards` | `stonks_cli.research.guards` | Fails closed for live execution unless the venue is allowed and explicitly armed. |
| `append_decision` / `read_decisions` | `stonks_cli.research.journal` | JSONL decision journal that can back the markdown ledger. |
| `decode_ws_message` / `IngestionMonitor` / `capture_hyperliquid_to_files` | `stonks_cli.research.ingestion` | Hyperliquid websocket fixture decoding plus Linux-hosted live capture health/drop accounting before the 7-day capture gate. |
| `rank_wallets` | `stonks_cli.research.attribution` | Venue-neutral wallet attribution from trade outcomes and funding events, with caveats before public leaderboard validation. |
| `PaperAnalysisEngine` | `stonks_cli.research.paper_analysis` | Paper-only mirror decisions with follower-bankroll size-down, stop-losses, cooldowns, and ledger-ready risk metadata. |

## Live Arm Gate

Hyperliquid live execution must be explicitly armed with:

```text
STONKS_CLI_HYPERLIQUID_LIVE_ARMED=armed
```

Paper and dry-run modes do not require an arm flag. Live mode does. Polymarket, Kalshi, and sportsbook execution are blocked for SG dogfooding and are not valid stonks-cli live venues.

## Long-Running Host

Any stonks-cli task that must keep running without sleep or shutdown is operated from the always-on Linux validation machine. MacBook runs are acceptable for development and fixture smoke checks, but they are not accepted as completion evidence for #13, #14, #10, or future uninterrupted roadmap gates.

## Reuse Map

| Existing primitive | Reuse path |
| --- | --- |
| `src/stonks_cli/scheduler/` | Continue running periodic capture, ranking, and paper replay jobs. |
| `src/stonks_cli/config.py` | `stonks-cliConfig` now records the Hyperliquid venue, arm gate, ledger path, live budget, and scale gate. |
| `src/stonks_cli/storage.py` and `src/stonks_cli/paths.py` | Continue providing state directories for journals and fixtures. |
| `src/stonks_cli/plugins.py` | Keep plugin loading available for later venue adapters. |
| `rust/hotpath` | Keep as the future low-latency state cache and guarded order construction layer. |
| Existing Polymarket journal / tearsheet ideas | Reuse the audit and tearsheet discipline, not SG live execution. |
