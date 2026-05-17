# WhaleMirror Runtime Primitives

Status: accepted on 2026-05-17.

The Phase 1 runtime keeps the existing scheduler, config, storage, plugin loader, journal discipline, and Rust hotpath, but new WhaleMirror surfaces use venue-neutral models first. Hyperliquid is the first concrete venue.

## Venue-Neutral Interfaces

| Primitive | Module | Purpose |
| --- | --- | --- |
| `NormalizedTrade` | `stonks_cli.whalemirror.models` | Common decoded trade shape for Hyperliquid now and future SG-legal venues later. |
| `ExecutionIntent` | `stonks_cli.whalemirror.models` | Paper, dry-run, or live order intent before venue submission. |
| `AttributionMetrics` | `stonks_cli.whalemirror.models` | Wallet ranking metrics: expectancy, Sharpe, decay, survivorship-adjusted PnL, and funding-adjusted PnL. |
| `DecisionRecord` | `stonks_cli.whalemirror.models` | Journal and ledger record for signal-to-decision-to-outcome traceability. |
| `evaluate_execution_guards` | `stonks_cli.whalemirror.guards` | Fails closed for live execution unless the venue is allowed and explicitly armed. |
| `append_decision` / `read_decisions` | `stonks_cli.whalemirror.journal` | JSONL decision journal that can back the markdown ledger. |

## Live Arm Gate

Hyperliquid live execution must be explicitly armed with:

```text
STONKS_CLI_HYPERLIQUID_LIVE_ARMED=armed
```

Paper and dry-run modes do not require an arm flag. Live mode does. Polymarket, Kalshi, and sportsbook execution are blocked for SG dogfooding and are not valid WhaleMirror live venues.

## Reuse Map

| Existing primitive | Reuse path |
| --- | --- |
| `src/stonks_cli/scheduler/` | Continue running periodic capture, ranking, and paper replay jobs. |
| `src/stonks_cli/config.py` | `WhaleMirrorConfig` now records the Hyperliquid venue, arm gate, ledger path, live budget, and scale gate. |
| `src/stonks_cli/storage.py` and `src/stonks_cli/paths.py` | Continue providing state directories for journals and fixtures. |
| `src/stonks_cli/plugins.py` | Keep plugin loading available for later venue adapters. |
| `rust/hotpath` | Keep as the future low-latency state cache and guarded order construction layer. |
| Existing Polymarket journal / tearsheet ideas | Reuse the audit and tearsheet discipline, not SG live execution. |

