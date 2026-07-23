# stonks-cli

Encrypted, local-first portfolio intelligence for personal equity, ETF, cash, and paper-research accounts.

It stores immutable encrypted source imports and a canonical transaction ledger, then reports holdings, cash, reconciliation, exposure, and performance. The first provider is Moomoo OpenD; portable CSV imports and provider plugins use the same contracts.

No command, plugin capability, MCP tool, or scheduler can unlock an account or submit/modify/cancel an order. Manual trading stays in the broker app.

## Public command contract

`stonks-cli` exposes only these commands:

- Profiles and imports: `init-profile`, `import-csv`, `import-prices`
- Portfolio reports: `portfolio`, `transactions`, `performance`, `reconciliation`
- Profile maintenance: `backup-profile`, `restore-profile`, `rotate-key`
- Portable encrypted reports: `recipient-key-add`, `recipient-key-revoke`, `recipient-key-list`, `report-export`, `report-export-audit`
- Research and operator utilities: `backtest-csv`, `strategy-*`, `watchlist`, `watchlist-configure`, `refresh-moomoo-prices`, `refresh-moomoo-quotes`, `scan-alerts`, `monitor`, `ml-*`, `research-*`, `llm-*`, `paper-*`, `schedule-*`, `notify-local`, `notify-telegram`, `telegram-recipient-add`, `telegram-configure`, `telegram-settings`, `telegram-send`, `telegram-delivery-audit`
- Integrations and metadata: `plugins`, `enable-provider`, `disable-provider`, `dividend-configure`, `drawdown-configure`, `moomoo-sdk-status`, `moomoo-probe`, `moomoo-accounts`, `moomoo-sync`, `moomoo-cash-flows`, `moomoo-dividends`, `moomoo-dividend-status`, `moomoo-map-dividend`, `version`

`stonks-mcp` is the separate MCP server entrypoint. All commands and tools are read-only,
local-data management, reporting, notification, or simulation interfaces; none can unlock an
account or submit, modify, or cancel an order.

Linux schedules use persistent user `systemd` timers. Confirm systemd and timezone, then inspect
`systemctl --user status`, `systemctl --user list-timers`, and service logs; catch-up occurs only
after the Pi boots, never while it is powered off.

On macOS, `schedule-install` writes a private LaunchAgent and bootstraps it with `launchctl`;
inspect it with `schedule-status` or `launchctl print gui/<uid>/com.stonks-cli.<profile>`.

For either scheduler, report content and its terminal-delivery status are encrypted in the profile;
retrieve the latest content with `schedule-artifact`.

## Start

```console
$ stonks-cli init-profile personal --key-file /absolute/path/personal.key
$ stonks-cli import-csv personal /absolute/path/export.csv --key-file /absolute/path/personal.key
$ stonks-cli portfolio personal --key-file /absolute/path/personal.key
```

`init-profile` generates a 256-bit key file with private permissions. Losing the key makes encrypted data unrecoverable. This private repository has no public license.

## Raspberry Pi workflow

Use the Pi only for read-only monitoring. Before enabling a timer, run each command manually and confirm its output.

```console
$ uv sync --extra moomoo
$ stonks-cli init-profile personal --key-file /absolute/path/personal.key
$ stonks-cli moomoo-sdk-status
$ stonks-cli moomoo-probe
$ stonks-cli moomoo-accounts
$ stonks-cli watchlist-add personal SPY US USD --name "S&P 500 ETF"
$ stonks-cli refresh-moomoo-prices personal --days 90
$ stonks-cli refresh-moomoo-quotes personal
$ stonks-cli scan-alerts personal --threshold-percent 5
$ stonks-cli ml-train personal US SPY
$ stonks-cli ml-rank personal --minimum-validation-accuracy 0.5
$ stonks-cli paper-deposit personal 10000 USD
$ stonks-cli monitor personal
```

`moomoo-probe` must succeed on the host running `monitor`. OpenD is restricted to a loopback endpoint; this CLI does not connect a Pi to OpenD on another machine. If OpenD cannot run on the Pi, run the read-only workflow on a supported local machine or import permitted CSV data manually.

Set Telegram secrets outside profiles and source control:

```console
$ export STONKS_CLI_TELEGRAM_TOKEN='...'
$ export STONKS_CLI_TELEGRAM_CHAT_ID='...'
$ stonks-cli monitor personal
```

`monitor` sends only public ticker, date, and price-move information. It never sends account identifiers, holdings, transactions, credentials, or an order instruction. Install the persistent Singapore-time Linux timer only after a manual monitor run succeeds:

```console
$ stonks-cli schedule-install personal
$ stonks-cli schedule-status personal
```

The ML model is a local price-only experimental baseline with chronological validation. Its probability is research output, not a profit forecast or a trading instruction.

## Optional LLM research

The LLM layer is disabled until configured. It supports loopback-only Ollama first, then OpenAI,
Anthropic, and Gemini APIs when `--allow-cloud` explicitly acknowledges their provider policy.
Credentials stay in environment variables; profiles retain only an environment-variable name, model,
loopback endpoint, and a user-supplied SGD estimate. Prompts and generated text are never stored;
only encrypted provider/model/token/estimated-cost metadata is retained.

```console
$ OLLAMA_NO_CLOUD=1 ollama serve
$ stonks-cli llm-configure personal ollama <installed-model> --ollama-local-only
$ stonks-cli llm-status personal
$ stonks-cli llm-news-summary personal /absolute/path/public-article.txt --source-url https://publisher.example/article
$ stonks-cli llm-explain-candidates personal --minimum-validation-accuracy 0.5
```

For a cloud API, configure its exact model and key environment variable, then set a daily or monthly
SGD ceiling using your provider's current model-specific input/output prices. `--budget-period none`
leaves no fixed cap. Price estimates are not billing statements.

```console
$ export OPENAI_API_KEY='...'
$ stonks-cli llm-configure personal openai <model> --allow-cloud --budget-period monthly --budget-limit-sgd 20 --input-cost-per-million-sgd <input-price> --output-cost-per-million-sgd <output-price>
```

`llm-chat` rejects obvious private-data markers. `llm-news-summary` requires a public HTTPS source
URL, and `llm-explain-candidates` sends only public ticker-level price-model metrics. The app never
sources holdings, account identifiers, balances, transaction data, credentials, or broker controls
into these requests; do not put them into a manually supplied question or article. Generated text can
be wrong and is not an educated forecast or personal advice.

`llm-agent-prompt` produces a manual, public-input-only argv for Codex, Claude Code, or Pi; it never
starts an agent or a scheduler. Run it outside directories containing private data. Their
subscription/API spending and sandbox controls remain external. The Ollama endpoint must be local
loopback, and `--ollama-local-only` requires disabling Ollama cloud features first: use the Pi when
available, otherwise run the same local workflow on the Mac. Remote Ollama endpoints are rejected.

## Broker reconciliation

Choose the account ID shown by `moomoo-accounts`; `moomoo-sync` never unlocks an account or
uses any mutation-capable OpenD method. It archives raw fills and broker snapshots encrypted,
normalizes only completed fills, and keeps broker cash/positions as observations for comparison.

```console
$ stonks-cli moomoo-sync personal 123456 --start 2026-07-01 --end 2026-07-22
$ stonks-cli reconciliation personal
```

OpenD timestamps use its configured timezone. Set `--opend-timezone` to that exact IANA zone;
the default is `Asia/Singapore`. `moomoo-cash-flows` retains the broker's documented flow type,
direction, amount, and dates, but does not silently map free-text flow labels into ledger events.
Moomoo documents that cash-flow queries are unavailable for paper accounts and Moomoo US accounts.

## Dividend receipts

`moomoo-dividends` archives announcement records only. A declared per-share amount or payment date
does not create available cash. To credit a dividend, first enable the per-profile setting, import the
cash flow and a current funds snapshot with `moomoo-sync`, then inspect exact local IDs with
`moomoo-dividend-status`. `moomoo-map-dividend` requires an explicit declaration-to-flow map,
record-date holding evidence, a settled inflow, the latest funds snapshot, and an explicit funds
reconciliation confirmation. Currency conversion additionally requires both the profile setting and
an exact user-supplied conversion rate.

```console
$ stonks-cli dividend-configure personal --allow-explicit-credit --allow-currency-conversion
$ stonks-cli moomoo-dividends personal 123456 SPY US USD
$ stonks-cli moomoo-cash-flows personal 123456 --clearing-date 2026-07-22
$ stonks-cli moomoo-dividend-status personal 123456
$ stonks-cli moomoo-map-dividend personal 123456 --declaration-id <id> --cash-flow-id <id> --cash-snapshot-id <id> --gross-currency USD --gross-amount 10 --withholding-amount 1 --confirm-reconciled-funds
```

Daily prices retain source revisions. OpenD historical daily bars require complete, ordered OHLC
values; legacy CSV imports may remain close-only, while CSVs that include any OHLC column must include
all three. `refresh-moomoo-quotes` performs only a one-shot OpenD
snapshot read; it creates no quote, order-book, order, or trade subscription. Raw snapshot payloads
are encrypted, and records include retrieval/as-of time, canonical US/SG market session plus the raw
provider state, bid/ask-derived spread, provider fingerprint, and subscription mode. Only an explicit
entitled, fresh, non-excessive-spread status can supply a current valuation; delayed, unavailable,
stale, malformed, unentitled, and unknown snapshots expose a status with no current price. Portfolio
JSON keeps `quote_snapshots` and `valuation_price_sources` separate from calculated values. Portfolio
allocation is reported separately by currency. Portfolio reporting defaults to SGD; import a sourced FX
CSV with `date,base_currency,quote_currency,rate` or retrieve MAS reference rates first. Each converted
cash or market value records its source currency, source value, rate provider, source hash, session date,
as-of time, and freshness. The default three-calendar-day limit is profile-configurable with
`fx-configure`; missing or stale FX leaves source-currency facts visible but withholds the
synthetic reporting-currency NAV total. `--base-currency` explicitly overrides the profile reporting
currency for that view.

## EOD universe

`universe-configure` stores versioned profile filters: US$5 individual-equity price floor, S$500,000
average daily traded-value floor across 15 of the latest 20 sessions, and 1% maximum fresh entitled
bid/ask spread by default. `import-liquidity` accepts sourced daily `date,identifier,currency,traded_value`
CSVs, and `universe-evaluate` reports every supported US/SG listed equity, ETF, or REIT as included or
excluded with its cash-eligibility, price, liquidity, quote, FX, source, as-of, and configuration facts.
Indexes, restricted products, unavailable inputs, delayed/unentitled quotes, and missing source data fail closed.

`refresh-mas-fx` retrieves the Monetary Authority of Singapore's published daily USD/SGD CSV for an
explicit date range. It accepts only the daily S$-per-US$ response contract, persists each noon-SGT rate
with MAS provenance, and encrypts the exact downloaded CSV before storing any rate. It retains only dates
inside the requested range; a malformed, empty, duplicate, or non-positive response stores no rate.

```console
$ stonks-cli import-fx personal /absolute/path/usd-sgd.csv
$ stonks-cli refresh-mas-fx personal 2026-07-01 2026-07-22
$ stonks-cli fx-configure personal --maximum-age-calendar-days 3
$ stonks-cli portfolio personal --base-currency SGD --json
```

## Research artifacts

`backtest-csv` writes an encrypted run card and result. Supply `--benchmark-return` only when you
have independently calculated the benchmark return for the same period; the default `0` is cash,
not a market benchmark. `strategy-journal` records the manual rationale for later review.

## Strategy settings

`strategy-settings` displays the active, versioned strategy contract and encrypted change audit.
The default risk tolerance is `balanced`, but advisory output remains disabled until it is explicitly
confirmed with `strategy-configure`. Defaults are growth, dividend income, then capital preservation;
a one-to-two-year horizon; 50% individual equities, 25% REITs, and 25% broad-index ETFs; and a
75% US / 25% Singapore split in each asset class. Cash-funded, long-only US/SG listed common equity,
non-levered/non-inverse ETF, and REIT boundaries cannot be relaxed. Listing and Moomoo cash-eligibility
checks remain required.

```console
$ stonks-cli strategy-configure personal --settings '{"risk_tolerance":"balanced","advisories_enabled":true}'
$ stonks-cli strategy-settings personal
```

`--settings` accepts a partial JSON object for configurable values. The baseline uses price trend as
the primary algorithm, with relative-strength and dividend-quality ranking enabled; two completed
closes below the 200-day SMA; a 25% drawdown threshold; a 5 percentage-point rebalance observation;
5% individual/REIT/sector/narrow/unknown caps; 20% broad-index ETF caps; no cash reserve; and
signal-directed, case-by-case dividend reinvestment. Conservative and balanced profiles may produce a manual sell
advisory on a risk breach; growth profiles remain alert-only. This release stores and exposes policy
only; it does not generate or execute recommendations.

## Reference benchmarks

Each profile stores a versioned, non-tradable reference blend: 75% `US:SPX` (S&P 500 Index, USD)
and 25% `SG:STI` (Straits Times Index, SGD). Components record an explicit canonical identifier,
source URL, currency, return basis, and weight; `benchmark-configure` replaces the full component
set from repeated JSON `--component` values, while `benchmark-settings` displays the active version.
Benchmark configuration is never a held-security inference or a trade recommendation. Total-return
series import accepts sourced `date,identifier,currency,total_return_index` CSVs; optional
`as_of_at,provider_id` fields retain data provenance. `benchmark-performance` uses exact start/end
total-return levels and exact-date FX records for the profile reporting currency, and reports
`unavailable` or `stale` rather than calculating from missing inputs. Legacy `benchmarks` profile entries remain
stored for compatibility but are not used as reference components.

`benchmark-templates` displays informational (not personalised investment-advice) comparisons for the
default US/Singapore blend, global equity, global listed real estate, US dividend growth, and US aggregate
bonds. Sources captured on 2026-07-23 are [S&P 500](https://www.spglobal.com/spdji/en/indices/equity/sp-500/),
[Straits Times Index](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/straits-times-index-ground-rules.pdf),
[MSCI ACWI](https://www.msci.com/indexes/index/892400/msci-acwi-index),
[FTSE EPRA Nareit Developed](https://research.ftserussell.com/Analytics/FactSheets/temp/aad58f07-6527-411d-a871-99f09b77afa4.pdf),
[VIG](https://investor.vanguard.com/investment-products/etfs/profile/vig), and
[AGG](https://www.ishares.com/us/products/239458/ishares-core-us-aggregate-bond-etf). `benchmark-template-import`
requires a sourced total-return observation for each selected component before activation and records encrypted
source provenance, retrieval time, data status, components, and configuration version. `benchmark-configure`
creates or edits a custom blend and records the same local audit fields.

`research-candidates` stores encrypted, deterministic ML screening artifacts. Each item is labelled
`research_candidate` with `experimental_price_only_model` and `no_execution` flags; it is never a
broker instruction, allocation target, or automated action. `strategy-advisory-journal-*` stores
profile-scoped encrypted manual advisory dispositions and may link only an imported posted buy/sell
ledger fingerprint; it cannot submit, alter, or cancel a broker order.

`stonks-mcp` exposes read status plus confirmation-bound local CSV import, provider configuration,
and encrypted backup. Confirmation IDs are single-use and expire after five minutes; MCP exposes no
broker mutation capability.
