(A) 2026-06-21 Write product decision: CarryMirror funding/basis carry is first live-candidate path; WhaleMirror copy-trading remains research only +CarryMirror @docs
(A) 2026-06-21 Add SG venue policy doc: allow MAS-licensed spot/fiat rails, mark Hyperliquid paper-first, block Polymarket/Kalshi/sportsbooks/Bybit until reviewed +Legal @docs
(A) 2026-06-21 Add config model for carry mode with default paper=true live_armed=false max_total_live_usd=0 +CarryMirror @config
(A) 2026-06-21 Add legal blocklist enforcement in CLI startup for blocked venue ids and blocked strategy classes +Legal @repo
(A) 2026-06-21 Add CarryQuote model with venue asset spot_mid perp_mid oracle_mid mark_mid timestamp source_health +CarryMirror @models
(A) 2026-06-21 Add FundingSnapshot model with asset venue hourly_rate annualized_rate next_funding_time premium_index timestamp +CarryMirror @models
(A) 2026-06-21 Add BasisSnapshot model with asset spot_mid perp_mid basis_abs basis_pct annualized_basis timestamp +CarryMirror @models
(A) 2026-06-21 Add CarryOpportunity model with asset venue direction net_apr gross_apr fee_bps slippage_bps buffer_bps required_fields_missing +CarryMirror @models
(A) 2026-06-21 Add CarryPosition model with asset spot_qty perp_qty net_delta entry_basis accrued_funding fees margin_buffer liquidation_distance +CarryMirror @models
(A) 2026-06-21 Add CarryDecision ledger model with decision_id mode action reason inputs risk_checks expected_net_apr exit_rule timestamp +CarryMirror @models
(A) 2026-06-21 Choose storage backend SQLite or DuckDB and document retention limits for 56GB SD card +Pi @storage
(A) 2026-06-21 Implement bounded snapshot tables for funding basis quotes decisions positions and venue health +CarryMirror @storage
(A) 2026-06-21 Add retention job that compacts old raw snapshots and keeps derived aggregates for Pi SD safety +Pi @ops
(A) 2026-06-21 Extend Hyperliquid client to fetch funding history predicted funding mids mark prices and spot/perp metadata +Hyperliquid @connector
(A) 2026-06-21 Extend Hyperliquid websocket ingestion to record allMids and relevant asset contexts into carry snapshots +Hyperliquid @connector
(A) 2026-06-21 Add data completeness validator that rejects opportunity calculations with stale missing or cross-timestamp inputs +Risk @data
(A) 2026-06-21 Implement net APR calculator subtracting funding fees slippage rebalance cost borrow/carry cost and volatility buffer +CarryMirror @calc
(A) 2026-06-21 Add BTC and ETH scanner command stonks-cli carry scan --venue hyperliquid --paper +CarryMirror @cli
(A) 2026-06-21 Add JSON and table output for carry scan with explicit missing-field caveats +CarryMirror @cli
(A) 2026-06-21 Add threshold config min_net_apr annualized default 15pct for research only not profit claim +Risk @config
(A) 2026-06-21 Implement paper entry simulator for spot-long plus perp-short funding carry +Paper @engine
(A) 2026-06-21 Implement paper exit simulator for funding flip net_apr drop delta drift margin buffer stale data and kill switch +Paper @engine
(A) 2026-06-21 Add paper fill model with configurable maker/taker fees slippage and missed-fill probability +Paper @engine
(A) 2026-06-21 Add funding accrual engine that applies hourly funding to simulated perp leg +Paper @engine
(A) 2026-06-21 Add delta monitor that blocks positions when abs net_delta exceeds configured tolerance +Risk @engine
(A) 2026-06-21 Add margin monitor that blocks entries below configured liquidation-distance and margin-buffer floors +Risk @engine
(A) 2026-06-21 Add stale-data gate that blocks decisions when websocket or REST health age exceeds 30s +Risk @engine
(A) 2026-06-21 Add daily weekly and global drawdown gates default 0.5pct 1.5pct 3pct +Risk @engine
(A) 2026-06-21 Add no-auto-raise guard so live notional caps cannot increase from strategy output +Risk @config
(A) 2026-06-21 Add ledger writer for every skipped entered exited and killed carry decision +Audit @ledger
(A) 2026-06-21 Add reconciliation report comparing simulated position state ledger and latest venue/account state +Audit @reports
(A) 2026-06-21 Add command stonks-cli carry paper run with duration state-dir report and ledger options +Paper @cli
(A) 2026-06-21 Add fixture tests for positive funding entry negative funding skip and funding flip exit +Tests @paper
(A) 2026-06-21 Add fixture tests for stale data max notional drawdown delta drift and missing hedge blocks +Tests @risk
(A) 2026-06-21 Add fixture tests for ledger rows on skip entry exit kill and reconciliation mismatch +Tests @audit
(A) 2026-06-21 Add 30-day paper gate doc with pass criteria: positive net expectancy after costs no unresolved mismatches no risk breaches +Paper @docs
(A) 2026-06-21 Add systemd service for Pi carry paper runner with restart policy watchdog and bounded logs +Pi @ops
(A) 2026-06-21 Add Pi install runbook covering uv env secrets file state dir logrotate watchdog active cooling and backup +Pi @docs
(A) 2026-06-21 Add health command stonks-cli carry health checking disk free RAM clock drift network venue APIs and stale streams +Pi @cli
(A) 2026-06-21 Add alert sink config for Telegram or email on kill switch stale data ledger mismatch and service restart +Ops @alerts
(A) 2026-06-21 Run 7-day dry Pi soak with scanner only and record CPU RAM disk growth reconnects and data gaps +Pi @validation
(A) 2026-06-21 Run 30-day paper carry gate on Pi for BTC and ETH only +Paper @validation
(A) 2026-06-21 Review SG legal posture before live: Hyperliquid terms MAS status DPT rails tax recordkeeping and prohibited venue list +Legal @review
(A) 2026-06-21 Choose live capital source and cap total first-live risk to USD 50-200 only after paper gate passes +Live @risk
(A) 2026-06-21 Implement live executor behind STONKS_CLI_CARRY_LIVE_ARMED with default disabled and separate secrets path +Live @executor
(A) 2026-06-21 Add live preflight requiring paper gate pass legal review recorded fresh venue health and manual cap confirmation +Live @risk
(A) 2026-06-21 Implement live order planner that creates matched spot/perp intents before submitting either leg +Live @executor
(A) 2026-06-21 Implement live partial-fill handler that exits or hedges if only one leg fills within timeout +Live @executor
(A) 2026-06-21 Implement live reduce-only exit path and block venues/order types that cannot express required safety flags +Live @executor
(A) 2026-06-21 Add live reconciliation loop that halts trading on account state mismatch position mismatch or missing ledger row +Live @audit
(A) 2026-06-21 Run 60-day tiny-live validation with USD 50-200 cap and no automatic scale +Live @validation
(A) 2026-06-21 Require seven green weeks and zero unresolved risk incidents before any manual scale proposal +Live @validation
(B) 2026-06-21 Research regulated-broker BTC/ETH ETF/futures basis APIs after Hyperliquid paper engine works +Broker @research
(B) 2026-06-21 Research cross-exchange funding only after single-venue paper and tiny-live evidence exists +CrossExchange @research
(B) 2026-06-21 Add abandon report template for negative paper expectancy repeated data gaps legal rejection or risk breach +Audit @docs
(B) 2026-06-21 Archive Polymarket-specific Rust live paths from active carry docs to avoid SG execution ambiguity +Legal @docs
(C) 2026-06-21 Keep WhaleMirror wallet activity shortlist as research input only and block it from live target selection +WhaleMirror @risk
