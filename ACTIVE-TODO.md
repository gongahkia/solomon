# ACTIVE-TODO

Code is no longer the bottleneck. Empirical calibration is.

## Phase 1 — Paper soak (1-2 weeks)
- [ ] Re-import latest wallet trade CSV: `stonks-cli polymarket wallets import ~/poly_data/processed/trades.csv`
- [ ] Tighten wallet rank: `stonks-cli polymarket wallets rank --min-trades 200 --min-win-rate 0.75 --limit 30`
- [ ] Inspect whales for sanity: `stonks-cli polymarket wallets whales --min-notional 10000 --limit 50`
- [ ] Set `polymarket.paper=true`, `auto_trade_enabled=true` in config
- [ ] Start runtime: `stonks-cli polymarket run --cycles 100 --sleep-seconds 30`
- [ ] Daily: `stonks-cli polymarket journal --tearsheet`

## Phase 2 — Signal pruning
- [ ] After ≥50 round-trips, kill any signal with `expectancy < 0` or `sharpe < 0`:
  - if `wallet_copy` losing → raise `auto_trade_min_target_wallets` or tighten `min_win_rate` at rank time
  - if `scanner` losing → raise `auto_trade_min_score`
- [ ] If both losing → alpha thesis is wrong, do NOT arm live

## Phase 3 — Tune opt-ins on real PnL
- [ ] Toggle one knob at a time, soak ≥30 trades, compare tearsheets:
  - [ ] `kelly_sizing_enabled=true` (kelly_fraction default 0.25)
  - [ ] `vol_target_enabled=true` (vol_target_per_trade default 0.05)
  - [ ] `use_microprice_for_entry=true`
  - [ ] `hurst_filter_enabled=true` (hurst_max default 0.45)

## Phase 4 — Arm live (only if Phase 2 green)
- [ ] Set `polymarket.paper=false`, `live_min_order_notional_usd=5.0`
- [ ] Start with `max_total_notional=20.0`, `max_daily_loss=5.0`
- [ ] `export STONKS_CLI_POLYMARKET_LIVE_ARMED=1`
- [ ] Run for 24h, check `journal --by-signal`, halt with `polymarket emergency-stop` if drawdown > $5
- [ ] Scale `max_total_notional` 2x only after 7 consecutive green days

## Deferred (not ROI-positive right now)
- pykalshi/pmxt cross-PM arb — Kalshi is geo-blocked from SG
- Backtester — no historical Polymarket orderbook data available
- HTML tearsheet export — terminal table is sufficient
- More providers/strategies — equity surface is dead weight, do not revive

## Open code questions (only if Phase 1+2 reveal them)
- [ ] Does `risk.build_trade_proposal` deduct CLOB fee + gas before the entry-price gate? Verify by tracing a real auto-trade journal entry; fix if not.
- [ ] Latency budget: end-to-end ws→decision→`polymarket-cli create-order` round-trip. Add `polymarket rust bench` if Phase 4 shows missed fills vs copied wallets.
