# Product Decisions

Status: accepted on 2026-05-17.

This document records the active `stonks-cli` product posture.

## Decisions

| Area | Decision | Success Definition |
| --- | --- | --- |
| Public identity | `stonks-cli` is the project, package, repository, and documentation name. | No active interface or document uses a separate product brand. |
| Ledger format | Use a markdown ledger in this repository: `docs/decision-ledger.md`. | Every paper carry decision can be committed, reviewed, and replayed from repo history. |
| Long-running validation host | Any uninterrupted validation run uses the always-on Linux validation machine. | MacBook runs are development evidence only. |
| Live capital | Paper mode is the default. Tiny-live carry is capped at USD 50-200 after explicit preflight. | No path raises a live cap automatically. |
| License | MIT license plus visible no-financial-advice and venue-legality disclaimers. | Reuse is simple, and the project is not positioned as investment, gambling, legal, or tax advice. |
| SG legal posture | Funding/basis carry is the sole live-candidate path. Wallet analysis is research-only. Dogfooding and execution are constrained by [carry venue policy](carry-sg-venue-policy.md). | Runtime policy blocks Polymarket, Kalshi, sportsbooks, Bybit, prediction-market strategy classes, and wallet rankings as live target selection input. |

## Out-of-Scope Framing

`stonks-cli` is not an AI day-trading bot and does not claim unsupported alpha. Product language must stay grounded in measured costs, risk, and public losses.
