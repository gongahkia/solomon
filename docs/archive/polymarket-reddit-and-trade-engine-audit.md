# Polymarket Reddit And Trade-Engine Audit

> [!WARNING]
> Archived research only. This is not active Carry or stonks-cli execution guidance. SG policy blocks Polymarket execution and prediction-market strategy classes.

Date: 2026-04-24

## Source Structure

The pasted Reddit material describes three useful live-trading lessons:

- Fast BTC short-window markets reward WebSockets, compiled execution, tiny test sizing, and strategy-specific session windows.
- Paper trading overstates performance unless it simulates actual spread, slippage, partial fills, and re-entry behavior.
- Real live failures cluster around execution mechanics: stale prices, thin books, bad fills, repeated stop-loss re-entry, and missing kill switches.

The cloned `KaustubhPatange/polymarket-trade-engine` repository is a TypeScript/Bun BTC short-window bot. Its strongest reusable pieces are operational rather than strategic:

- Orderbook walking to estimate actual shares, average fill price, and unfilled notional from current asks/bids.
- A market lifecycle that tracks pending orders, order history, blocked buy/sell states, emergency sells, and recovery.
- A PID-style process lock to avoid duplicate bot instances.
- Indicator utilities for BTC short-window strategies, including RSI, ATR, RTV, and peak-gap checks.

## Implemented From These Sources

- Rust orderbook fill estimator: `rust/hotpath/src/book_math.rs`
- Rust scanner guard that rejects partial estimated entry fills and excessive entry slippage.
- Python config and fallback scanner parity for the same fill/slippage controls.
- Fill-estimate metrics on scan rows and execution/rejection journal entries.
- Runtime PID lock for the Rust control loop, preventing two live loops from trading the same state directory.
- Existing safeguards from prior phases already covered the other Reddit failure modes: stop-loss re-entry cooldown, total exposure caps, daily loss/profit stops, volume-spike exits, live arm flag, stale order cancellation, and emergency stop.

## Not Copied Directly

- The TypeScript/Bun execution client was not adopted because this repo now routes live order placement through the official Polymarket CLI from the Rust control plane.
- The BTC late-entry strategy was not copied as a default live strategy because it depends on external BTC price feeds, market-slot semantics, and tuning parameters that need separate validation before risking capital.
- The repo’s simulation-only strategies were not copied because the current priority is preventing live execution errors, not adding unproven signal count.

## Current Money-Making Implication

The system is closer to live-safe operation, but these changes do not prove profitability. They reduce non-strategy losses by refusing trades where the book cannot support the intended tiny order or where crossing the book would create a bad entry. Profitability still depends on signal quality: wallet targeting, category filters, consensus, research theses, and live validation on tiny size.

## Remaining High-Value Work Before Scaling

- Add a validated BTC short-window module only after wiring reliable BTC reference feeds and Polymarket slot parsing.
- Backtest or paper-replay strategy votes against captured WebSocket data before increasing order size.
