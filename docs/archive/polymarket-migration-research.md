# Polymarket Migration Research For `stonks-cli`

> [!WARNING]
> Archived research only. This is not active CarryMirror or WhaleMirror execution guidance. SG policy blocks Polymarket execution and prediction-market strategy classes.

## Purpose

This document translates the supplied Polymarket tutorial post into an implementation plan for this repository.

The current repository is a stock-analysis CLI with optional paper trading and MCP tooling. The tutorial describes a live, event-driven, multi-agent Polymarket trading system. Those are materially different systems. The correct approach is not a small feature addition. It is a controlled replacement of the runtime and strategy layer while preserving the useful parts of the existing repo: CLI ergonomics, config, plugin loading, MCP surface, logging, and tests.

## Executive Summary

The tutorial system has five layers:

1. Offline data mining on historical Polymarket trades to identify strong wallets.
2. A live scanner over active Polymarket markets and order books.
3. A decision engine that combines structural signals, news, wallet-following, and cognitive-bias heuristics.
4. An execution layer that uses focused agents and consensus gating.
5. An exit engine that closes before settlement based on target capture, volume spikes, and stale-thesis logic.

`stonks-cli` today does not do that. It is optimized for:

- Daily-bar stock data
- Technical-indicator strategies
- Batch analysis and report generation
- Human-readable reports
- Paper trading by ticker

It is not optimized for:

- Real-time event markets
- Order-book microstructure
- Token-level Polymarket execution
- Multi-process or async agent orchestration
- Sub-second reaction loops
- Position and exit logic specific to binary event contracts

The repo does already have a useful foothold: `src/stonks_cli/data/polymarket.py` proves Polymarket data access is already conceptually accepted in the codebase. But the current provider only fetches cached daily history. That is far below what the tutorial bot needs.

## What The Tutorial Actually Implements

The post describes a system built from four external repos plus an LLM:

### 1. `poly_data`

Role:

- Historical trade lake
- Wallet profitability analysis
- Target wallet selection

Output:

- A target list of profitable wallets
- Historical patterns for entry and exit behavior

Why it matters:

- The strategy is not pure event prediction.
- The edge is partly meta-trading: predict and follow informed traders.

### 2. `polymarket-cli`

Role:

- Low-friction market discovery
- Market metadata retrieval
- Order-book inspection
- Midpoint pricing
- Potential execution path

Why it matters:

- The scanner depends on current live market state, not historical candles.
- The tutorial uses JSON CLI output as the live data feed.

### 3. `Polymarket/agents`

Role:

- Framework for market fetch, LLM analysis, position tracking, and trading hooks

Why it matters:

- It provides the architecture for a decision loop, not just data access.

### 4. `Polymarket-Trading-Bot`

Role:

- Strategy modules
- Execution patterns
- Order management

Why it matters:

- The tutorial borrows concrete execution behavior from an implementation that already targets Polymarket microstructure.

### 5. LLM (`Claude`)

Role in the post:

- Wallet filtering prompt
- Market scoring prompt
- Thesis generation
- Bias detection
- Kelly sizing scaffolding

Important implementation reading:

- In the tutorial, the LLM is presented as the glue.
- In production, the LLM cannot sit directly on the hot path for every trade if low latency matters.
- The practical interpretation is: use the LLM offline or asynchronously for research, labeling, ranking, category logic, and strategy generation, but keep execution-time scoring deterministic.

## Core Strategy Logic Extracted From The Post

The strategy is a pipeline:

### A. Build a target wallet universe

Filter historical wallets by:

- `trades >= 100`
- `win_rate > 70%`
- sort by profit
- keep top N

Implication:

- The system depends on a local, queryable historical trade dataset.

### B. Scan active markets

For each active market, calculate or fetch:

- midpoint price
- order-book depth
- hours to resolution
- a model estimate of probability

Discard markets where:

- edge is too thin
- book depth is too small
- resolution is too close
- resolution is too far out

Implication:

- This is a market queue builder, not a final trade decision system.

### C. Run a decision engine on the surviving queue

Checks mentioned in the post:

- base rate
- recent news
- whale presence
- crowd cognitive error

Gate:

- at least 3 of 4 checks agree
- confidence threshold
- Kelly sizing capped at quarter Kelly

Implication:

- The decision engine is multi-signal and probabilistic.
- It should be decomposed into independently testable evaluators.

### D. Use multi-agent consensus for entry

Agents in the post:

- arbitrage
- convergence
- whale copy

Gate:

- 2 agreeing agents -> full size
- 1 agreeing agent -> half size
- disagreement -> no trade

Implication:

- We need a first-class vote object, not one monolithic strategy output.

### E. Exit before settlement

Exit triggers in the post:

- 85% of expected move captured
- abnormal volume spike
- stale thesis after 24h

Implication:

- Positions need their own active monitoring loop.
- Holding to settlement should not be the default.

## What `stonks-cli` Does Today

Current repo intent from `README.md` and code:

- “batteries-included stock analysis CLI”
- daily-price fetching
- technical analysis
- report generation
- backtesting
- schedule-based recurring runs
- watchlists, alerts, portfolio, paper trading
- MCP server tools

Execution shape today:

1. CLI or MCP entrypoint
2. load config
3. choose a provider per ticker
4. fetch daily data, mostly in threads
5. attach indicators
6. run a single strategy function per ticker
7. produce recommendations and reports
8. optionally record run state

Critical current files:

- `src/stonks_cli/cli.py`
- `src/stonks_cli/commands.py`
- `src/stonks_cli/pipeline.py`
- `src/stonks_cli/config.py`
- `src/stonks_cli/data/providers.py`
- `src/stonks_cli/data/polymarket.py`
- `src/stonks_cli/mcp_server.py`
- `src/stonks_cli/portfolio/paper.py`

Key architectural properties:

- synchronous or thread-pooled batch execution
- provider API centered on `fetch_daily(ticker)`
- strategy API centered on `Recommendation(action, confidence, rationale)`
- report-first outputs
- no event bus
- no order manager
- no live positions monitor
- no async network runtime

## Gap Analysis: Tutorial Bot vs Current Repo

### 1. Domain Model

Current repo:

- ticker-centric
- equity OHLCV oriented
- daily timeframe

Tutorial bot:

- market/token-centric
- binary event contract oriented
- order-book and event-time oriented

Impact:

- Existing `PriceProvider.fetch_daily()` is the wrong abstraction for the live bot.

### 2. Runtime

Current repo:

- batch runs
- cron scheduling
- report generation

Tutorial bot:

- daemon processes
- continuous monitoring
- concurrent agents
- stateful positions loop

Impact:

- `schedule run` is insufficient as the primary engine.
- We need a long-running service mode.

### 3. Strategy Interface

Current repo:

- one strategy per ticker
- indicator-driven
- single recommendation output

Tutorial bot:

- scanner + brain + executor + exit monitor
- multiple agents voting independently
- stateful market lifecycle

Impact:

- Current strategy interface is too narrow.

### 4. Data Access

Current repo:

- cached HTTP reads
- daily history
- optional providers

Tutorial bot:

- active markets
- order books
- midpoint
- live wallet activity
- recent volume

Impact:

- Current Polymarket provider is insufficient.

### 5. Execution

Current repo:

- paper buy/sell based on fetched last price
- no live order placement abstraction

Tutorial bot:

- limit-order placement in a CLOB
- price-aware entries
- partial fills
- cancel/replace logic

Impact:

- Execution must be rebuilt.

### 6. Latency Budget

Current repo:

- optimized enough for CLI analysis
- not optimized for reaction speed

Tutorial bot:

- low latency matters
- stale news or slow decisions destroy edge

Impact:

- LLM calls must not sit in the critical path.

## Repository Components Worth Keeping

Even if most trading logic is replaced, these parts remain useful:

### Keep

- `cli.py`
  - mature command surface and Typer integration
- `config.py`
  - existing config persistence and validation
- `plugins.py`
  - useful for strategy or provider extensions
- `logging_utils.py`
  - reusable observability layer
- `mcp_server.py`
  - valuable for Codex/Claude interoperability
- test layout and CI structure

### Replace Or Heavily Refactor

- `pipeline.py`
  - built for batch analysis, not live trading
- `analysis/*`
  - mostly stock indicator logic, low reuse value
- `portfolio/paper.py`
  - share-based equity semantics do not map cleanly to binary contracts
- `data/polymarket.py`
  - needs a broader client and lower-latency runtime behavior
- `scheduler/*`
  - useful only for auxiliary jobs, not the main trading loop

## Recommended Target Architecture

The target system should be a Polymarket-first trading engine with a CLI and MCP wrapper around it.

### Top-level modules to introduce

- `src/stonks_cli/polymarket/client.py`
  - Polymarket API and CLOB client wrapper
- `src/stonks_cli/polymarket/models.py`
  - market, token, order book, trade, position, signal, vote, execution result
- `src/stonks_cli/polymarket/cache.py`
  - lightweight in-memory and on-disk caches for non-hot-path metadata
- `src/stonks_cli/polymarket/scanner.py`
  - active market queue builder
- `src/stonks_cli/polymarket/wallets.py`
  - target wallet tracking and wallet signal extraction
- `src/stonks_cli/polymarket/brain.py`
  - deterministic signal fusion and thesis generation
- `src/stonks_cli/polymarket/agents.py`
  - arbitrage, convergence, whale-copy evaluators
- `src/stonks_cli/polymarket/risk.py`
  - Kelly sizing, caps, portfolio exposure, category caps
- `src/stonks_cli/polymarket/executor.py`
  - limit order placement, order reconciliation, cancel/replace
- `src/stonks_cli/polymarket/exits.py`
  - exit monitor loop
- `src/stonks_cli/polymarket/runtime.py`
  - async service orchestration
- `src/stonks_cli/polymarket/storage.py`
  - positions, fills, journals, run state

### Runtime model

Recommended runtime:

- one async process
- multiple async tasks
- shared in-memory state
- durable append-only journal for recovery

Core tasks:

1. market discovery loop
2. order-book refresh loop
3. wallet signal loop
4. decision loop
5. execution loop
6. exit monitor loop
7. metrics and health loop

Reason:

- Separate OS processes with file-based coordination are simple, but shared-memory async tasks are lower latency and easier to reason about for order coordination.

## Low-Latency Design Principles

This is the main implementation constraint from the user request.

### Principle 1: Keep the hot path deterministic

Hot path means:

- market refresh
- book scoring
- wallet-follow signals
- entry gating
- price selection
- exits

These should be plain Python logic with no LLM call.

### Principle 2: Use the LLM only off-path

Good LLM uses:

- generate or revise scoring heuristics offline
- classify market categories
- summarize news for operator review
- label historical data
- generate post-trade diagnostics
- help create strategy plugins

Bad LLM uses:

- asking Claude whether to buy every live market
- using Claude to score the order book before every placement

### Principle 3: Reduce network round trips

- batch fetch market lists when possible
- only deep-refresh books for shortlisted markets
- cache static market metadata
- avoid repeated slug-to-condition lookups
- reuse sessions

### Principle 4: Treat wallet-copy latency as first-class

- wallet copy only works if ingestion lag is low
- polling frequency and parsing overhead matter
- copy trading should be category-scoped, not global

### Principle 5: Journal every state transition

- discovered
- queued
- evaluated
- ordered
- partially filled
- filled
- exited
- cancelled

This is essential for correctness under restart.

## Bring Your Own Key Design

The user asked for bring-your-own-key if possible.

Recommended config additions:

- Polymarket wallet private key or signing credentials
- optional read-only mode without trading credentials
- optional LLM provider selection
- `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` compatibility
- explicit mode flags:
  - `read_only`
  - `paper`
  - `live`

Suggested config shape:

```json
{
  "engine": {
    "mode": "paper",
    "loop_interval_ms": 500,
    "max_active_markets": 64
  },
  "polymarket": {
    "enabled": true,
    "private_key_env": "POLYMARKET_PRIVATE_KEY",
    "chain_id": 137,
    "min_market_depth_usd": 50000,
    "min_edge_bps": 700
  },
  "llm": {
    "provider": "openai",
    "model": "gpt-5.4",
    "api_key_env": "OPENAI_API_KEY",
    "enabled_for_research": true,
    "enabled_for_hot_path": false
  }
}
```

Implementation note:

- Do not store private keys directly in config files.
- Store env var names in config and read actual secrets at runtime.

## Claude/Codex Optimization

The user asked for Claude and Codex optimization where possible.

The right interpretation is:

- expose the system cleanly through CLI and MCP
- make strategies modular and inspectable
- make configs explicit
- make logs structured
- let agents query status, positions, queue, and recent trades

Recommended MCP additions:

- `polymarket_list_markets`
- `polymarket_scan_queue`
- `polymarket_get_wallet_targets`
- `polymarket_get_positions`
- `polymarket_run_once`
- `polymarket_start_runtime`
- `polymarket_stop_runtime`
- `polymarket_place_paper_order`
- `polymarket_get_health`
- `polymarket_get_journal`

## What I Would Not Copy Directly From The Post

### 1. LLM in the main trade loop

Reason:

- too slow
- too expensive under scale
- too non-deterministic

### 2. Shell-script orchestration as the main runtime

Reason:

- acceptable for a prototype
- weak recovery, coordination, and state management

### 3. Blind trust in claimed results

Reason:

- the post provides no verifiable audit trail
- the system design may still be useful even if the PnL claims are overstated

### 4. Generic “news” as an unbounded live dependency

Reason:

- high latency
- noisy
- difficult to test

Replace with:

- optional, bounded news adapters
- category-specific feeds
- low-frequency enrichment rather than hot-path dependency

## Proposed Migration Plan

### Phase 0: Documented design and cut lines

Deliverables:

- this research doc
- module plan
- config plan
- command plan

### Phase 1: Build a Polymarket core without live trading

Deliverables:

- robust Polymarket client
- market list fetch
- order-book fetch
- midpoint and depth calculation
- market normalization
- queue builder
- deterministic scanner tests

CLI examples:

- `stonks-cli polymarket markets list`
- `stonks-cli polymarket scan`
- `stonks-cli polymarket book <token>`

### Phase 2: Add historical wallet intelligence

Deliverables:

- import path for `poly_data`-style exports
- wallet ranking job
- target wallet store
- wallet signal extraction

CLI examples:

- `stonks-cli polymarket wallets import trades.csv`
- `stonks-cli polymarket wallets rank`
- `stonks-cli polymarket wallets targets`

### Phase 3: Add paper runtime

Deliverables:

- async runtime
- paper order manager
- position tracking for binary contracts
- exit monitor
- structured journal

CLI examples:

- `stonks-cli polymarket run --paper`
- `stonks-cli polymarket status`
- `stonks-cli polymarket positions`

### Phase 4: Add multi-agent consensus

Deliverables:

- arbitrage evaluator
- convergence evaluator
- whale-copy evaluator
- vote fusion
- Kelly and exposure controls

### Phase 5: Add live execution

Deliverables:

- authenticated trading
- order placement
- cancel/replace
- fill reconciliation
- kill switch

CLI examples:

- `stonks-cli polymarket run --live`
- `stonks-cli polymarket orders`
- `stonks-cli polymarket emergency-stop`

## Recommended First Implementation Slice

The fastest high-value first slice is:

1. Keep the existing repo shell.
2. Add a new `polymarket` command group.
3. Build a new Polymarket client package.
4. Implement scanner primitives:
   - list active markets
   - fetch order books
   - compute midpoint
   - compute depth
   - filter by liquidity and resolution
5. Implement a paper-only runtime with deterministic scoring.
6. Add journaled state and tests.

Why this slice first:

- it produces a working system quickly
- it validates the data path
- it avoids irreversible live trading mistakes
- it gives us latency measurements before adding complexity

## Proposed Command Surface

Suggested new commands:

```text
stonks-cli polymarket markets list
stonks-cli polymarket markets show <slug_or_token>
stonks-cli polymarket scan
stonks-cli polymarket wallets import <trades.csv>
stonks-cli polymarket wallets rank
stonks-cli polymarket runtime start --paper
stonks-cli polymarket runtime status
stonks-cli polymarket positions
stonks-cli polymarket orders
stonks-cli polymarket journal tail
stonks-cli polymarket doctor
```

## Testing Strategy

### Unit tests

- market normalization
- midpoint calculation
- depth calculation
- queue filtering
- Kelly sizing
- vote fusion
- exit trigger logic

### Integration tests

- scan loop over mocked market payloads
- paper runtime order lifecycle
- restart recovery from journal
- CLI command smoke tests

### Performance tests

- queue build latency
- book refresh latency
- decision latency
- runtime memory profile

Success criteria for the hot path:

- no LLM dependency
- bounded per-loop latency
- deterministic output for fixed inputs

## Concrete Diff: Current Repo vs Tutorial Post

### Current repo assumptions

- end user wants analysis reports
- primary assets are stocks
- data cadence is daily
- strategy evaluation is stateless per run
- execution is optional and simplified

### Tutorial assumptions

- end user wants continuous autonomous trading
- primary assets are Polymarket event contracts
- data cadence is live
- strategy evaluation is stateful and multi-agent
- execution and exits are the product, not an add-on

### Bottom line

To match the tutorial, `stonks-cli` should become:

- less a report generator
- more a trading runtime with CLI tooling

The repo name can stay. The architecture cannot.

## My Recommendation

Use `stonks-cli` as the shell, not the core.

Keep:

- CLI
- config
- plugin system
- MCP
- logging
- tests

Replace:

- stock-centric analysis pipeline
- equity-oriented paper portfolio model
- daily-provider assumptions
- report-first scheduler flow

The right target is a Polymarket-first, async, paper-then-live engine with deterministic low-latency decisioning and optional LLM-assisted research outside the hot path.

## Language And Runtime Decision

This section incorporates official Polymarket documentation and SDK status checked on April 24, 2026.

### What Polymarket officially supports

Polymarket officially provides CLOB SDKs in:

- TypeScript
- Python
- Rust

It also provides WebSocket feeds for near real-time market and user data, including:

- full order book snapshots
- price change events
- last trade events
- best bid / ask updates
- market resolution events

That means the latency-sensitive path should be built around WebSockets, not periodic REST polling, regardless of language.

### Is Polymarket “largely based on timing”?

Partly, yes, but not uniformly.

Strategies where timing matters a lot:

- market making
- top-of-book quoting
- short-horizon crypto markets
- copy trading with low delay
- order-book arbitrage

Strategies where timing matters less:

- offline wallet discovery
- trader ranking
- market categorization
- medium-horizon convergence and queue building
- post-trade analytics

So the correct statement is:

- Polymarket is timing-sensitive in the execution and market-data path.
- It is not purely a raw-speed contest across the entire system.

### Why not switch the whole repo to Rust immediately?

Rust is stronger than Python for:

- sustained websocket ingestion
- lower tail latency
- memory efficiency
- safer concurrent execution
- execution daemons that must stay hot and predictable

But rewriting everything to Rust immediately would slow delivery in the wrong places:

- historical CSV analysis
- experimentation
- strategy iteration
- CLI integration in this existing repo

Those parts are not where the main latency edge lives.

### Why not Go or C?

Go:

- viable for services and concurrency
- but Polymarket’s official SDK support is centered on TypeScript, Python, and Rust
- using Go would mean more custom protocol and auth maintenance

C:

- not a serious recommendation here
- no official SDK path
- much higher implementation risk
- negligible practical trading edge over a well-built Rust executor for this use case

### Recommended architecture after research

The best tradeoff is a hybrid:

- Python for orchestration, historical analytics, wallet mining, strategy research, operator tooling, and MCP
- Rust for the future live execution daemon if we decide we need lower and more predictable latency than Python can deliver

In other words:

- Python is not the fastest language.
- Python is fast enough for Phase 2 wallet intelligence and structural scanning.
- Rust is the best candidate for the eventual hot execution engine.

### Current recommendation

Do not rewrite the entire repo to Rust yet.

Do this instead:

1. Continue Phase 2 in Python for wallet intelligence and research pipelines.
2. Move Phase 4 or Phase 5 execution into a separate Rust service if:
   - websocket throughput becomes a bottleneck
   - cancel/replace latency becomes strategy-critical
   - copy-trade delay materially hurts fills
   - market-making becomes a core strategy

This keeps us on the fastest path to a useful system without locking the execution path into Python forever.
