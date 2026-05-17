# Product Decisions

Status: accepted on 2026-05-17.

This document resolves the pre-Phase 1 decisions from the pivot plan so WhaleMirror work can proceed without naming, ledger, license, live-capital, or legal-posture ambiguity.

## Decisions

| Area | Decision | Success Definition |
| --- | --- | --- |
| Public identity | WhaleMirror is the product name. The installable package and current GitHub repository stay `stonks-cli` until a deliberate repository rename is performed. | Public docs lead with WhaleMirror, while package commands remain stable for existing local workflows. |
| Ledger format | Use a markdown ledger in this repository: `docs/decision-ledger.md`. | Every paper or live mirror decision can be committed, reviewed, and replayed from repo history before any separate static site exists. |
| Live-armed Phase 1 capital | Paper mode is the default. The initial live-armed Phase 1 budget is capped at USD 200, with sub-USD 50 per-order notional until the scale gate is met. | No code or doc path raises notional automatically before the 60-day live gate and 7 consecutive green weeks are satisfied. |
| License | MIT license plus visible no-financial-advice and venue-legality disclaimers. | Reuse is simple, and the project is not positioned as investment, gambling, legal, or tax advice. |
| SG legal posture | Dogfooding and execution are constrained to SG-legal venues. The project does not execute on Polymarket, Kalshi, sportsbooks, or circumvention-based venues from Singapore. | README and runbooks cannot be read as instructions to open or execute restricted prediction-market or sportsbook positions from SG. |

## Out-of-Scope Framing

WhaleMirror is not an AI day-trading bot and does not claim unsupported alpha. Product language must stay grounded in expectancy, Sharpe, decay, survivorship-adjusted PnL, funding, slippage, and public losses.

