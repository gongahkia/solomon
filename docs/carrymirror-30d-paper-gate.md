# CarryMirror 30-Day Paper Gate

Status: accepted for GitHub issue #23.

CarryMirror cannot progress to tiny live execution until a continuous 30-day paper run satisfies all pass criteria.

## Pass Criteria

| Gate | Pass Requirement |
| --- | --- |
| Net expectancy | Positive net expectancy after funding, fees, slippage, rebalance cost, borrow/carry cost, and volatility buffer. |
| Reconciliation | Zero unresolved mismatches between paper state, audit ledger, and latest venue/account state. |
| Risk firewall | Zero unresolved risk breaches for stale data, missing hedge, delta drift, margin buffer, liquidation distance, drawdown, max notional, or live-cap auto-raise. |
| Auditability | Every skip, entry, exit, kill, and mismatch has a ledger row with expected funding, fees, slippage, basis, margin buffer, risk checks, and exit reason where applicable. |
| Operation | Run duration is 30 days without manual state edits or hidden restarts. |

Passing this paper gate is necessary, not sufficient, for live use. Legal, venue, custody, tax, and operational review still block live progression until separately cleared.

Post-gate broker-basis and cross-exchange research is governed by [CarryMirror post-gate research](carrymirror-post-gate-research.md).
