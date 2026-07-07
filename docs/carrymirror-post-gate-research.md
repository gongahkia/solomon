# CarryMirror Post-Gate Research

Status: accepted for GitHub issue #26.

Do not start this research until the Hyperliquid single-venue paper gate and tiny-live evidence exist.

## Research Gate

| Topic | Earliest Start | Must Include |
| --- | --- | --- |
| Regulated broker BTC/ETH ETF/futures basis APIs | After Hyperliquid paper engine has durable positive/negative evidence and no unresolved ledger mismatches. | SG legal/terms review, custody analysis, tax recordkeeping, data retention, Pi operational impact. |
| Cross-exchange funding | After single-venue paper gate and 60-day tiny-live evidence. | API-key custody review, venue blocklist review, transfer/collateral risk, latency/partial-fill model, Pi soak plan. |
| EdgeFinder expansion | After CarryMirror live validation and separate approval. | SG-legal venue list, capital caps, one-click execution arm flag, public opportunity ledger. |

## Non-Blocking Rule

These research tracks do not unblock initial Hyperliquid CarryMirror work. They must not delay scanner, paper engine, audit ledger, Pi ops, or tiny-live safety work.

## Required Proposal Template

Any expansion proposal must record:

- Research date and operator.
- Venue/entity names and jurisdiction.
- Legal/terms review owner and result.
- Custody/key-management impact.
- Pi runtime impact: CPU, RAM, disk growth, network, service restart behavior, backup.
- Data gaps and stale-data behavior.
- Reconciliation and ledger changes.
- Capital cap and no-auto-scale proof.
- Abandon criteria from [CarryMirror abandon report template](carrymirror-abandon-report-template.md).

## Abandon Criteria

Abandon or pause if any item appears:

- Negative net expectancy after funding, fees, slippage, borrow/carry cost, and volatility buffer.
- Repeated data gaps or stale venue state.
- Legal, terms, tax, custody, or venue rejection.
- Risk breach, unresolved reconciliation mismatch, or missing ledger row.
- Net APR vanishes after realistic costs.
