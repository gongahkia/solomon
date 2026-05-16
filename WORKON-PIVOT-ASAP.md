# WORKON-PIVOT-ASAP

Three-phase product pivot plan. Replaces the equity-CLI + generic-MCP + Polymarket framing currently in the repo.

This document is the single source of truth for the pivot. `ACTIVE-TODO.md` Phase 4 ("arm live" against Polymarket) is now **legally non-viable from Singapore** as of GRA's Jan 2025 block and should be treated as deprecated, not executed.

---

## 1. Why pivot

### 1.1 Current repo positioning is unsellable

Three product surfaces stitched together:
- generic stock analysis CLI — owned by OpenBB (~67k stars), commodified, yfinance-fragile
- MCP server for stock data — saturated (Alpha Vantage, MarketXLS, Alpaca, TradingView, Financial Datasets, ContextCraft, etc.)
- Polymarket copy-trading bot — the most differentiated surface, but:
  - alpha is empirically thin (~7.6% of Polymarket wallets profitable, copy-trading whales documented to underperform)
  - regulatory dead-end from SG as of Jan 2025

### 1.2 What retail-trading tools demonstrably work

Empirically (97% of futures retail loses; 99% of day traders fail over 5y), the few categories where retail consistently makes money are:
- buy-and-hold (no software needed)
- tax-loss harvesting / direct indexing (cost-reduction, not alpha)
- wheel/covered calls on quality stocks (1–3%/mo)
- information edges that decay fast (congressional trades ~6% 30d, options flow when filtered)
- structural arb (cross-venue spreads, funding-rate arb)
- riding wallets with real edge before others copy them

The pivot targets the last two — both compatible with the existing Rust hotpath + execution-guardrails work.

### 1.3 Why "honest math" is itself a moat

The retail trading-tool market is dominated by SEO-spam, "AI bot" launches, and signal services that promise alpha. A tool that:
- shows survivorship-adjusted PnL
- publishes its own losses
- frames itself as "arbitrage / EV" rather than "alpha"
- ships a public live ledger of decisions and outcomes

…stands out specifically because the field is so saturated with scams. The honesty is the differentiation.

### 1.4 Singapore residency hard-constrains venue choice

| Venue | SG status |
|---|---|
| Polymarket | Blocked, close-only since Jan 2025 (GRA, illegal gambling) |
| Kalshi | Explicitly geo-blocked |
| Major sportsbooks | Illegal under GCA 2022 (fine SGD 10k + 6mo prison) |
| Hyperliquid | Fully accessible; SG = #2 traffic source (~7.45%) |
| Solana / EVM DEXes | Fully accessible, wallet-only |
| US stock options (IBKR SG, Tiger SG) | Fully legal |
| Crypto perps CEXes (OKX, Bybit) | Mostly accessible |

GCA 2022 has extraterritoriality and treats VPN circumvention as continuation of the offense. **All three pivot phases must use only SG-legal venues for dogfooding and execution.**

---

## 2. Pivot phases

```
Phase 1 -> WhaleMirror, Hyperliquid only
Phase 2 -> WhaleMirror branched to other SG-legal venues
Phase 3 -> EdgeFinder (SG-legal variant) layered on top
```

### 2.1 Core principle: dogfooding is non-negotiable

Every venue we integrate must satisfy two tests:
1. legally usable by an SG resident with no circumvention
2. operable as the developer's own live test account, not just a paper feed

If a venue fails either, it goes in the "ship a connector for users but skip dogfooding" bucket, and that's a flag, not a default.

### 2.2 Honest-math principles (apply to all three phases)

- attribution math reports **expectancy**, **sharpe**, **decay** (rolling-window sharpe), and **survivorship-adjusted** PnL — not just win-rate
- every signal/wallet/spread has a public **decision ledger** (timestamp, rationale, exec receipt, outcome)
- the product never claims alpha it cannot show with a ledger
- losses are published as visibly as wins

---

## 3. Phase 1 — WhaleMirror (Hyperliquid)

### 3.1 What it does

Multi-wallet copy-observability and execution on Hyperliquid:
- ingest the full Hyperliquid trade stream (perps + spot)
- rank wallets honestly (expectancy, sharpe, decay curves, not lazy win-rate filters)
- mirror selected wallets' trades to the user's own Hyperliquid account with risk caps, paper-first then armed
- journal every decision; publish tearsheet

### 3.2 Reuse from existing repo

| Existing | Reuse for Phase 1 |
|---|---|
| `rust/hotpath` state cache + guarded order construction | Port to Hyperliquid orderbook + order semantics |
| `rust/hotpath` order lifecycle tracking | Reuse as-is |
| Polymarket arm-flag pattern (`STONKS_CLI_POLYMARKET_LIVE_ARMED`) | Rename to `STONKS_CLI_HYPERLIQUID_LIVE_ARMED`, same gate |
| Heartbeat / emergency-stop / consensus voting | Reuse architecture; rewire venue calls |
| Journal + tearsheet | Reuse as-is |
| APScheduler + cron runtime | Reuse as-is |
| Paper-trading engine | Reuse for paper-mirror mode |
| `polymarket wallets rank` semantics | Generalize to `wallets rank` venue-agnostic, Hyperliquid-first impl |

### 3.3 Build from scratch

- Hyperliquid websocket ingestion (sub-second trade detection)
- Hyperliquid REST/WS order client (create / cancel / sync open orders)
- decoded perp event log -> normalized internal trade model
- wallet attribution: survivorship-adjusted sharpe, decay-window expectancy, leverage-adjusted PnL
- Hyperliquid funding-cost accounting (perp PnL is incomplete without funding)
- size-down logic: cap mirror notional as % of follower's bankroll, not target's
- stop-loss / re-entry cooldown wired against Hyperliquid mark price

### 3.4 Delete / archive

To stop the equity sprawl from dragging on the pivot:

- archive `src/stonks_cli/charts/`, `src/stonks_cli/analysis/`, equity-side pipeline, `analyze` / `backtest` / `bench` / `data` / `watchlist` / `signals` CLI surfaces
- archive equity MCP tools (`get_fundamentals`, `get_news`, `get_earnings`, etc.)
- keep `paper_buy`, `paper_sell`, journal, tearsheet — generalize for Hyperliquid
- keep config / scheduler / plugin scaffolding
- README rewrite: lead with WhaleMirror, mention equity surface only as deprecated

### 3.5 Acceptance gates (in order; do not skip)

1. **Connector gate**: 7 days of clean Hyperliquid trade-stream capture, no drops, all decode tests pass
2. **Attribution gate**: rank top-100 Hyperliquid wallets; manually sanity-check the top 10 against `hyperdash.info` / `hyperliquid.xyz` leaderboards
3. **Paper-mirror gate**: 30 days paper-mirroring top 5 wallets; tearsheet shows non-trivial PnL (positive or negative — gate is "is the simulation realistic", not "is it profitable")
4. **Latency gate**: end-to-end target-trade-detected to mirror-order-placed under 800ms p95. If we cannot hit this, document it honestly and pivot the framing from "fast copy" to "considered copy with attribution math"
5. **Live-armed gate**: 60 days live-armed with sub-$50 notional caps; tearsheet vs paper to validate slippage model
6. **Scale gate**: only raise notional caps after 7 consecutive green weeks (mirrors existing Polymarket discipline from `ACTIVE-TODO.md`)

### 3.6 Risks specific to Phase 1

| Risk | Mitigation |
|---|---|
| Latency race with funded closed-source bots | Reframe pitch from "fastest mirror" to "honest mirror with decay-aware attribution"; latency under 800ms is good enough for non-HFT followers |
| Hyperliquid TOS / wallet-tracking norms shift | Track Hyperliquid governance; respect any explicit copy-trading rules |
| Whale edge decays mid-mirror | Decay-window sharpe explicitly rotates wallets out; built into ranker |
| Front-running by larger copy-bots | Size-down + entry-price guard already in repo; port to Hyperliquid mark price |
| MAS posture on retail DEX trading shifts | Monitor; current MAS focus is DTSPs and stablecoins, not retail DEX access |

### 3.7 Phase 1 done = ship criteria

- public GitHub repo renamed (suggestion: `whalemirror` or keep `stonks-cli` as the umbrella; decide before public push)
- HN-ready story: "I built a Rust-backed Hyperliquid copy-mirror with honest decay attribution and 60 days of public live PnL"
- live PnL ledger published (markdown table in repo, auto-updated)
- README has tearsheet screenshot + replayable fixture + paper-mode quickstart

---

## 4. Phase 2 — WhaleMirror branched to other SG-legal venues

Triggered only after Phase 1 acceptance gates pass.

### 4.1 Candidate venue order

Prioritized by (SG accessibility) × (wallet-attribution feasibility) × (incremental work over Phase 1):

1. **Solana memecoin wallets** — wallet-only, on-chain, SG-accessible. Execution via Jupiter / Raydium aggregators. Different decode work (SPL transfers vs perp events) but same attribution math.
2. **EVM perp DEXes** (dYdX, GMX, Vertex) — wallet-only, SG-accessible. Order semantics overlap with Hyperliquid; smaller per-venue work after Phase 1.
3. **Crypto perp CEXes** (OKX, Bybit) — SG-accessible with KYC. Adds CEX API key custody surface (security burden). Wallet-tracking less meaningful (CEX users opaque); becomes "strategy mirror", not "wallet mirror".
4. **Pump.fun / Bonk.fun memecoin launches** — extremely high decay, useful only as a Phase-2-late research surface.

### 4.2 Explicitly out of scope for Phase 2

- Polymarket (close-only, illegal new positions from SG)
- Kalshi (geo-blocked)
- sportsbooks (criminal exposure under GCA 2022)
- prediction markets that take USDC stakes on event outcomes (GRA classifies as gambling regardless of front-end)

### 4.3 Phase 2 deliverable

`whalemirror` becomes a multi-venue copy-observability layer with a unified attribution model. The product story shifts from "Hyperliquid copy-mirror" to "honest on-chain wallet mirror across venues."

### 4.4 Risks specific to Phase 2

- decode complexity per venue compounds (each chain / DEX has its own log format)
- attribution math must remain comparable across venues despite different fee/funding models
- security surface grows with CEX API keys; consider deferring CEXes to Phase 3

---

## 5. Phase 3 — EdgeFinder (SG-legal variant)

Triggered only after Phase 2 ships and stable.

### 5.1 What it does — narrower than original EdgeFinder

Original EdgeFinder (Polymarket vs Kalshi vs sportsbook spreads) is **not buildable from SG**. SG-legal variant focuses on cross-venue math that doesn't touch prediction markets or sportsbooks:

1. **Crypto perp funding-rate arbitrage** across Hyperliquid / Binance / OKX / Bybit. Funding rates routinely disagree by 5–30 bps; long-low-funding short-high-funding is delta-neutral.
2. **Crypto options volatility surface arbitrage** — Deribit vs OKX options on BTC/ETH. Same underlying, different IV.
3. **Equity cross-listing / ADR spreads** — HK vs US listings of the same name (BABA, NIO, BIDU, etc.). SG has full broker access to both.
4. **Options vs perp basis** — when implied vol on Deribit + perp funding diverge from a no-arb relationship.

### 5.2 Why this is a real product even narrowed

- audience is sophisticated (sharpens the honest-math pitch)
- spreads exist mechanically (different user bases, different fees, different geographies)
- no regulatory ambiguity — all venues are SG-legal
- complements WhaleMirror: WhaleMirror = ride others' edge; EdgeFinder = own math

### 5.3 Reuse from Phase 1+2

- Rust hotpath = same low-latency scanner, retargeted
- attribution math = becomes per-venue spread tracking + Kelly-sized recommendation
- journal + tearsheet = same
- arm-flag execution gate = same pattern
- multi-venue connector layer from Phase 2 = directly reused

### 5.4 Phase 3 done = ship criteria

- SG-legal multi-venue scanner producing ranked +EV opportunities
- public ledger of opportunities flagged + outcomes
- one-click execution to whichever venue the user has connected
- documented "what we cannot reach" page (Polymarket / Kalshi / sportsbooks) with the legal rationale, because being upfront about it builds trust

---

## 6. What to delete from the current repo (Phase 0)

Pre-work before Phase 1 starts. Goal: stop carrying dead weight.

### 6.1 Remove or archive

- `src/stonks_cli/analysis/` — equity strategies
- `src/stonks_cli/charts/` — equity chart helpers
- equity surfaces of `pipeline.py`
- `analyze` / `backtest` / `bench` / `signals` CLI commands
- equity MCP tools
- equity provider plugins (yfinance, Finnhub, Alpaca data-only, Stooq, Tiger as data source)
- `pyproject.toml` extras: `yfinance`, `tiger`, `finnhub`, `alpaca`, `akshare`

### 6.2 Keep

- `src/stonks_cli/portfolio/` — paper trading engine (generalize, venue-agnostic)
- `src/stonks_cli/alerts/` — repurpose for wallet-decay alerts
- `src/stonks_cli/scheduler/` — runtime loop
- `src/stonks_cli/plugins.py` — plugin scaffolding
- `src/stonks_cli/config.py` — pydantic config
- `src/stonks_cli/storage.py` — history/journal
- `rust/hotpath` — port forward
- MCP server framing — narrow to WhaleMirror tools only

### 6.3 Rename

Decide before public push:
- Option A: rename repo to `whalemirror` (clearer wedge)
- Option B: keep `stonks-cli` as umbrella, sub-brand WhaleMirror inside it
- recommend Option A; sharper story, no equity baggage in the name

---

## 7. Open decisions (decide before Phase 1 starts)

1. **Repo rename or keep?** (see 6.3)
2. **Public ledger format?** Markdown auto-update in repo, or separate static site?
3. **Funding source for live-armed Phase 1?** How much capital to commit to first 60 days. Recommend $200–500 to make slippage realistic without catastrophic downside
4. **License?** Current is implicit. For an honest-math copy-trader, MIT-style + visible disclaimer is appropriate. AGPL if we want to discourage closed-source SaaS forks
5. **Disclaimer / legal posture for SG users?** Add a SG-specific notice: "this tool does not execute on Polymarket / Kalshi / sportsbooks from SG; venue list is constrained to SG-legal venues"

---

## 8. Out of scope forever (do not revive)

Sticking with the discipline from `ACTIVE-TODO.md`:

- equity surface (commodified, OpenBB owns it)
- generic stock MCP (saturated)
- Polymarket execution from SG (illegal new positions)
- Kalshi (geo-blocked)
- sportsbook integration (criminal exposure for SG operator)
- "AI day-trading bot" framing of any kind — triggers scam BS-detector
- generic-LLM-summarizes-earnings retail tool (AlphaSense moat is data licensing, not summary quality)

---

## 9. Success metrics (revisit at each phase gate)

Not just "did we ship". Each phase's real success is measured by:

| Phase | Primary metric | Secondary |
|---|---|---|
| Phase 1 | 60d live-armed tearsheet beats paper-mirror baseline within slippage tolerance | GitHub stars, HN reception |
| Phase 2 | Cross-venue attribution math passes sanity checks against public leaderboards | Number of venues with green per-venue tearsheets |
| Phase 3 | Spread-capture success rate vs flagged opportunities | First paying user (if monetized) |

---

## 10. Cross-references

- `ACTIVE-TODO.md` — pre-pivot Polymarket discipline; Phases 1–3 there are now superseded; Phase 4 ("arm live" against Polymarket) is legally non-viable from SG and is **canceled**
- `README.md` — to be rewritten after Phase 0 deletion pass
- `docs/polymarket-live-runbook.md` — archive as historical reference; do not execute from SG
