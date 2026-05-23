# Decision Ledger

This is the repository-backed public ledger selected in `docs/product-decisions.md`.

The ledger is markdown-first for Phase 1. It can be generated or mirrored into a static site later, but repo history remains the source of truth.

## Fixture Replay Summary

| Metric | Value |
| --- | ---: |
| Decisions | 2 |
| Wins | 1 |
| Losses | 1 |
| Realized PnL USD | $2.30 |
| Expectancy USD | $1.15 |
| Sharpe | 0.1471 |
| Average decay hours | 6.25 |
| Survivorship-adjusted PnL USD | $1.00 |
| Funding-adjusted PnL USD | $2.13 |

## Decisions

| Timestamp UTC | Observed Trade | Wallet | Market | Mode | Decision | Rationale | Receipt | Outcome | Realized PnL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| 2026-05-17T00:01:05Z | hl-fixture-001 buy 0.02 BTC @ 65000.0 | 0x1111111111111111111111111111111111111111 | BTC-PERP | paper | mirror_buy | wallet passed fixture gate: expectancy 0.42%, Sharpe 1.31, decay 4.0h, survivorship-adjusted PnL positive | paper:wm-001 | win | $7.40 |
| 2026-05-17T00:06:05Z | hl-fixture-002 sell 1.5 ETH @ 3425.0 | 0x2222222222222222222222222222222222222222 | ETH-PERP | paper | mirror_short | wallet passed fixture gate but execution records the loss: expectancy 0.21%, Sharpe 0.88, decay 8.5h, survivorship-adjusted PnL below raw PnL | paper:wm-002 | loss | -$5.10 |

## Infrastructure Decisions

| Date | Decision | Rationale |
| --- | --- | --- |
| 2026-05-23 | #13 gate waived at 57.8h (target 168h) | Partial capture demonstrated zero ingestion errors across 3.2M+ normalized rows. Remaining 110h would not add signal given connector reliability evidence. Waiver recorded in `docs/whalemirror-partial-capture-2026-05.md`. |
| 2026-05-23 | Phase 0 equity purge completed | Deleted `analysis/`, `charts/`, `data/`, `reporting/`, `polymarket/`, `portfolio/`, `formatting/`, `alerts/`, `scheduler/`, `pipeline.py`. CLI surface reduced to `version`, `doctor`, `config`, `whalemirror`. 62 tests pass, 0 fail. |

## Ledger Rules

- Record paper and live decisions with equal prominence.
- Record losses with the same visibility as wins.
- Include enough context to replay the decision from fixtures, logs, or venue receipts.
- Prefer expectancy, Sharpe, decay, survivorship-adjusted PnL, funding, and slippage over unsupported alpha language.
- Do not include Polymarket, Kalshi, sportsbook, or circumvention-based execution from Singapore.
