# stonks-cli Research Notes

## Current direction

`stonks-cli` evaluates Hyperliquid funding/basis carry through reproducible scans, a paper engine, a risk firewall, and an audit ledger. It does not present wallet analysis as a live-trading strategy.

## Active gate

GitHub issue #14 is the 30-day Hyperliquid paper carry gate. A passing run requires positive cost-adjusted expectancy, complete state/ledger/reconciliation evidence, zero unresolved risk breaches, and no live orders.

## Live posture

Tiny-live carry remains blocked until the paper gate, SG legal review, custody review, fresh venue health, and explicit preflight all pass. The configured cap must stay between USD 50 and USD 200; no command can increase it automatically.

## Deferred work

Multi-venue wallet copying and general opportunity scanners are not current roadmap commitments. They require a new issue and separate approval after the carry program has stable evidence.
