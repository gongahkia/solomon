# CarryMirror Research

Date: 2026-06-21

Scope: decide whether this repo should pursue autonomous trading, WhaleMirror, or funding/basis arbitrage as a Raspberry Pi 5 hosted income project for an SG resident.

Not financial, legal, tax, or accounting advice. I cannot verify any trading design that removes long-term loss risk.

## Decision

The best direction is not live WhaleMirror copy-trading first. The best direction is a conservative rewrite/pivot toward `CarryMirror`: a Pi-hosted delta-neutral funding and basis scanner, paper engine, risk firewall, and later tiny live executor.

Why:

- Whale-copying depends on finding wallets with durable alpha. The repo currently has activity capture and fixture ranking, not enough closed-position evidence to trust live mirroring.
- Directional autonomous trading has high base-rate failure. A cited day-trading study found persistent loss among retail futures day traders.
- Delta-neutral carry has a clearer economic source: funding/basis paid by levered directional demand. It is still not free money because of liquidation, collateral, venue, borrow, execution, and regime risk.
- The Pi 5 is enough for websocket capture, SQLite/DuckDB, scheduling, risk checks, alerts, and small order routing. It is not the edge source.

Target product:

```text
CarryMirror = SG-aware carry scanner + paper carry engine + risk firewall + audit ledger + optional tiny live executor
```

## Repo Fit

Current repo status:

- Python package: `stonks-cli`, Python `>=3.11`, Typer CLI, Pydantic config, APScheduler, pandas/numpy, rich, websockets.
- Current product identity: WhaleMirror.
- Current default: paper and dry-run only.
- Current active venue: Hyperliquid.
- Current legal posture: SG execution excludes Polymarket, Kalshi, sportsbooks, and circumvention-based venues.
- Current evidence: Hyperliquid connector ran 57.8h on Linux, decoded 3.2M+ normalized rows, zero malformed messages, zero dropped messages.
- Open gates: 30-day paper mirror and 60-day live validation remain open.
- Rust hotpath still contains old Polymarket-oriented code and should not drive new live SG execution without rewrite.

Reusable pieces:

- CLI structure and command registration.
- Config loading and validation.
- Hyperliquid websocket ingestion primitives.
- Paper-first guard pattern.
- Decision ledger pattern.
- Validation-gate reporting pattern.
- Tests and fixture style.

Pieces to de-emphasize or replace:

- Wallet-copying as first live strategy.
- Polymarket-specific Rust runtime.
- Any live path that auto-increases notional.
- Any SG-hosted instructions for Polymarket, Kalshi, sportsbooks, or restricted prediction-market access.

## Raspberry Pi Fit

Available hardware:

- Raspberry Pi 5, 4GB RAM.
- 56GB microSD.
- Always-on local device.

Fit:

- Good for continuous websocket ingestion, scheduled scans, SQLite/DuckDB state, lightweight risk rules, Telegram/email alerts, and small live order checks.
- Weak for indefinite raw market-data retention on microSD. A 56GB SD card can fill or wear if raw captures are left unbounded. Use retention, compression, compaction, and ideally external SSD before live operation.
- Active cooling and a reliable 5V/5A PSU matter for always-on Pi 5 operation.
- [Inference] At an assumed 10W continuous draw and SP Group Q2 2026 tariff of SGD 0.2972/kWh, power cost is about SGD 2.14/month. Actual draw depends on PSU, cooling, storage, and workload.

Pi role:

```text
observe -> calculate carry -> paper trade -> enforce risk gates -> alert -> optionally place tiny live orders
```

The Pi should not run discretionary ML, high-frequency trading, or latency-sensitive market making.

## Strategy Ranking

### 1. Delta-Neutral Funding Carry

Mechanic:

- Hold spot or spot-like exposure.
- Short the matching perpetual when funding paid to shorts is positive enough.
- Stay close to delta-neutral.
- Earn net funding after fees, slippage, borrow/carry cost, and rebalancing.

Best first implementation:

- Hyperliquid scanner and paper engine.
- Start with BTC and ETH only.
- No leverage above 1x effective notional during paper and tiny live phases.
- No directional fallback trades.
- No cross-margin scale until long paper evidence exists.

Main risks:

- Funding flips negative.
- Perp basis moves against the account.
- Spot/perp mark divergence creates margin stress.
- Venue outage blocks hedge or exit.
- Liquidation despite "delta-neutral" label.
- API bug or stale data causes wrong sizing.

Verdict: best fit for Pi and repo.

### 2. Regulated-Broker BTC/ETH Basis

Mechanic:

- Use regulated products such as ETFs/futures where available through a broker.
- Track basis and trade cash-and-carry only when net spread clears fees and margin.

Pros:

- Cleaner legal/compliance path than offshore crypto perps.
- Better statements and tax records.
- Less wallet/key custody risk.

Cons:

- Higher capital requirement.
- Broker APIs and market data may be harder than Hyperliquid.
- Pi still acts as scheduler/scanner, not exchange co-location.

Verdict: worth researching after Hyperliquid paper engine exists.

### 3. Cross-Exchange Funding Arbitrage

Mechanic:

- Long spot/perp on one venue.
- Short perp/spot on another venue.
- Earn spread between funding rates or basis.

Pros:

- More opportunities than one venue.

Cons:

- Collateral fragmentation.
- Withdrawal delays.
- Venue failure risk doubles.
- SG legal/terms review for every venue.
- More operational complexity than a first Pi deployment should carry.

Verdict: later only.

### 4. WhaleMirror Copy-Trading

Mechanic:

- Rank profitable wallets.
- Mirror with smaller size and risk caps.

Problems:

- Current shortlist is activity-derived, not profitability-derived.
- Public fills can hide full exposure, transfers, funding, fees, and off-chain context.
- High activity may be market making, liquidation flow, or hedging.
- Durable alpha can decay once copied.

Verdict: keep as observability and candidate research, not first live income path.

### 5. Directional Trading Bot

Mechanic:

- Predict direction and place trades.

Problems:

- Strong base-rate against retail/day-trading profitability.
- Hard to distinguish edge from overfit.
- Pi adds no special advantage.

Verdict: reject for this objective.

## Risk Firewall

Non-negotiable rules:

- Default mode is paper.
- Live mode requires an explicit arm flag and a separate config file.
- Strategy must be delta-neutral before any live order.
- BTC and ETH only until paper evidence justifies more markets.
- No naked long or naked short entries.
- No auto-sizing above configured caps.
- No auto-raise of caps based on short-term wins.
- Use isolated margin where available.
- Use reduce-only for exits where venue supports it.
- Treat stale market data as a hard block.
- Kill switch on daily loss, weekly loss, drawdown, stale data, missing hedge, venue degradation, or ledger mismatch.
- Every paper/live decision writes a ledger row with expected funding, fees, slippage, basis, margin buffer, and exit reason.

Initial caps:

- Paper: unlimited notional simulation, but track realistic fills.
- Tiny live: USD 50 to USD 200 total capital only after paper gates.
- Max deployed: 10% to 20% of total bankroll during first live period.
- Daily stop: 0.5% of bankroll.
- Weekly stop: 1.5% of bankroll.
- Global kill: 3% to 5% drawdown.
- Funding entry threshold: only enter when projected net APR exceeds fees, slippage, and a volatility buffer. A starting threshold of 15% annualized is reasonable for research, not a verified profit threshold.

Exit rules:

- Funding flips against position.
- Net APR falls below threshold.
- Margin buffer falls below configured floor.
- Spot/perp delta exceeds tolerance.
- Websocket or REST health stale beyond 30s.
- Venue rejects reduce-only exit or status degrades.
- Ledger and venue state mismatch.

## SG Legal/Tax Posture

Cannot verify legal clearance for live crypto-perp trading from Singapore. Treat this as research posture only.

Lower-risk posture:

- Use MAS-licensed Digital Payment Token providers for fiat/spot rails where possible.
- Avoid Polymarket, Kalshi, sportsbooks, and unlicensed remote gambling.
- Avoid venues on MAS Investor Alert List.
- Keep records for IRAS: deposits, withdrawals, fills, funding, fees, realized P&L, unrealized P&L snapshots, and bot logs.
- If activity becomes frequent/systematic or income-like, get SG tax/legal advice.

Venue posture:

| Venue class | Status | Reason |
| --- | --- | --- |
| MAS-licensed spot/fiat DPT rails | Preferred rails | Directly fits SG licensing framework for DPT services. |
| Regulated broker futures/ETF access | Candidate | Cleaner recordkeeping and product framework, but needs broker API/capital review. |
| Hyperliquid | Paper-first, tiny-live candidate only after review | Good API fit, but offshore DEX/perp legal and custody posture not fully verified. |
| Cross-exchange CEX perps | Later only | Each venue needs terms, MAS status, API-key, custody, and SG access review. |
| Bybit | Block until reviewed | MAS Investor Alert List result found for Bybit Fintech Limited dated 2026-06-17. |
| Polymarket/Kalshi/sportsbooks | Block | Repo already excludes SG execution; GRA remote gambling risk. |

Tax posture:

- IRAS materials distinguish capital gains from taxable trading/business income depending on facts.
- Frequent, systematic, income-seeking bot activity may be treated differently from personal capital gains.
- Keep full records from day zero.

## Engineering Plan

Phase 0: decision and policy

- Add this research doc.
- Add todo.txt action list.
- Write a product decision that CarryMirror is the first live-candidate path and WhaleMirror copy-trading remains research.
- Add SG venue whitelist/blocklist.

Phase 1: data model

- Add `CarryQuote`, `FundingSnapshot`, `BasisSnapshot`, `CarryOpportunity`, `CarryPosition`, `CarryDecision`.
- Store snapshots in SQLite or DuckDB with bounded retention.
- Normalize Hyperliquid funding, mark, oracle, spot, perp, and fee data.

Phase 2: scanner

- Scan BTC and ETH funding/basis.
- Compute net APR after funding, fees, slippage estimate, rebalancing cost, and buffer.
- Emit ranked opportunities.
- Refuse opportunities missing any required field.

Phase 3: paper engine

- Simulate delta-neutral entries and exits.
- Track funding accrual, slippage, fees, liquidation distance, and margin buffer.
- Run for 30 days on the Pi without manual intervention.

Phase 4: risk firewall

- Enforce stale-data, max-notional, max-drawdown, delta, margin, and venue-health gates.
- Add full ledger reconciliation.
- Add watchdog and systemd service.

Phase 5: tiny live

- Only after paper evidence.
- Start with USD 50 to USD 200 total risk capital.
- No cap increase until 60-day live evidence and seven green weeks, matching existing repo policy.

## Abandon Criteria

Stop this direction if any of these occur:

- 30-day paper carry has negative expectancy after realistic costs.
- Bot cannot stay delta-neutral under normal volatility.
- Data gaps or venue state mismatches occur repeatedly.
- Legal review says the chosen live venue path is not acceptable for SG residence.
- Live test breaches daily/weekly/global stop.
- Net APR opportunities vanish after costs for the target capital size.

## Sources

- Raspberry Pi 5 product/specs: https://www.raspberrypi.com/products/raspberry-pi-5/
- SP Group electricity tariffs: https://www.spgroup.com.sg/our-services/utilities/tariff-information
- Hyperliquid websocket subscriptions: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- Hyperliquid funding: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding
- Hyperliquid margining: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/margining
- Hyperliquid liquidations: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/liquidations
- Hyperliquid contract specs: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications
- CME crypto basis explainer: https://www.cmegroup.com/openmarkets/equity-index/2025/Spot-ETFs-Give-Rise-to-Crypto-Basis-Trading.html
- BIS crypto carry research: https://www.bis.org/publ/work1087.pdf
- Retail day-trading evidence: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- Singapore GRA unlawful remote gambling: https://www.gra.gov.sg/harm-minimisation/unlawful-remote-gambling-activities
- Singapore Payment Services Act: https://sso.agc.gov.sg/act/psa2019
- MAS DPT provider licensing/FID: https://eservices.mas.gov.sg/fid/institution?activity=Digital+Payment+Token+Service&category=Major+Payment+Institution&sector=Payments
- MAS Investor Alert List: https://www.mas.gov.sg/investor-alert-list
- Singapore Securities and Futures Act: https://sso.agc.gov.sg/act/sfa2001
- IRAS digital tokens and taxable income: https://www.iras.gov.sg/taxes/corporate-income-tax/income-deductions-for-companies/taxable-non-taxable-income
- IRAS gains from sale of financial instruments: https://www.iras.gov.sg/taxes/individual-income-tax/basics-of-individual-income-tax/what-is-taxable-what-is-not/gains-from-sale-of-property-shares-and-financial-instruments
