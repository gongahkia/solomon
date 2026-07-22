# stonks-cli

Encrypted, local-first portfolio intelligence for personal equity, ETF, cash, and paper-research accounts.

It stores immutable encrypted source imports and a canonical transaction ledger, then reports holdings, cash, reconciliation, exposure, and performance. The first provider is Moomoo OpenD; portable CSV imports and provider plugins use the same contracts.

No command, plugin capability, MCP tool, or scheduler can unlock an account or submit/modify/cancel an order. Manual trading stays in the broker app.

## Public command contract

`stonks-cli` exposes only these commands:

- Profiles and imports: `init-profile`, `import-csv`, `import-prices`
- Portfolio reports: `portfolio`, `transactions`, `performance`, `reconciliation`
- Profile maintenance: `backup-profile`, `restore-profile`, `rotate-key`
- Research and operator utilities: `backtest-csv`, `strategy-*`, `watchlist`, `refresh-moomoo-prices`, `refresh-moomoo-quotes`, `scan-alerts`, `monitor`, `ml-*`, `research-*`, `llm-*`, `paper-*`, `schedule-*`, `notify-local`, `notify-telegram`
- Integrations and metadata: `plugins`, `enable-provider`, `disable-provider`, `dividend-configure`, `moomoo-sdk-status`, `moomoo-probe`, `moomoo-accounts`, `moomoo-sync`, `moomoo-cash-flows`, `moomoo-dividends`, `moomoo-dividend-status`, `moomoo-map-dividend`, `version`

`stonks-mcp` is the separate MCP server entrypoint. All commands and tools are read-only,
local-data management, reporting, notification, or simulation interfaces; none can unlock an
account or submit, modify, or cancel an order.

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
$ stonks-cli schedule-install personal --hour-singapore 18
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

Daily prices retain source revisions. `refresh-moomoo-quotes` performs only a one-shot OpenD
snapshot read; it creates no quote, order-book, order, or trade subscription. Raw snapshot payloads
are encrypted, and records include retrieval/as-of time, market session, bid/ask-derived spread,
provider fingerprint, and subscription mode. Only an explicit entitled, fresh, non-excessive-spread
status can supply a current valuation; delayed, unavailable, stale, malformed, unentitled, and
unknown snapshots expose a status with no current price. Portfolio JSON keeps `quote_snapshots` and
`valuation_price_sources` separate from calculated values. Portfolio allocation is reported separately
by currency by default. To produce a base-currency view, import a sourced FX CSV with
`date,base_currency,quote_currency,rate` and request it explicitly; missing direct or inverse rates
fail the report rather than using an implied conversion.

```console
$ stonks-cli import-fx personal /absolute/path/usd-sgd.csv
$ stonks-cli portfolio personal --base-currency SGD --json
```

## Research artifacts

`backtest-csv` writes an encrypted run card and result. Supply `--benchmark-return` only when you
have independently calculated the benchmark return for the same period; the default `0` is cash,
not a market benchmark. `strategy-journal` records the manual rationale for later review.

`research-candidates` stores encrypted, deterministic ML screening artifacts. Each item is labelled
`research_candidate` with `experimental_price_only_model` and `no_execution` flags; it is never a
broker instruction, allocation target, or automated action.

`stonks-mcp` exposes read status plus confirmation-bound local CSV import, provider configuration,
and encrypted backup. Confirmation IDs are single-use and expire after five minutes; MCP exposes no
broker mutation capability.
