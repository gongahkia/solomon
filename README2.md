# stonks-cli v2 — Planned Changes

## Overview

Textual TUI + 4 new API providers (Tiger Trade, Polymarket, Finnhub, Alpaca). All existing CLI commands remain untouched except `watch` (migrated to Textual). New `stonks-cli tui` command launches full app.

---

## New Dependencies

| Package | Optional Group | Purpose |
|---------|---------------|---------|
| `textual>=0.89,<1.0` | `tui` | Terminal UI framework (replaces Rich Live) |
| `tigeropen>=3.0` | `tiger` | Tiger Trade SDK |
| `py-clob-client>=0.1` | `polymarket` | Polymarket CLOB client |
| `finnhub-python>=2.4` | `finnhub` | Finnhub REST client |
| `alpaca-py>=0.30` | `alpaca` | Alpaca Markets SDK |

New `all` group: `stonks-cli[tui,tiger,polymarket,finnhub,alpaca,yfinance,mcp]`

New entry point: `stonks-tui = "stonks_cli.tui.app:main"`

---

## New Files

### Data Providers

| File | Class | Auth | Notes |
|------|-------|------|-------|
| `src/stonks_cli/data/finnhub.py` | `FinnhubProvider` | `FINNHUB_API_KEY` env / config | REST `/api/v1/stock/candle`, extra: quote, profile, news |
| `src/stonks_cli/data/alpaca.py` | `AlpacaProvider` | `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` env / config | `alpaca-py` SDK, paper trade support |
| `src/stonks_cli/data/tiger.py` | `TigerProvider` | RSA key + tiger_id + account via config | `tigeropen` SDK, maps Tiger bar format to OHLCV |
| `src/stonks_cli/data/polymarket.py` | `PolymarketProvider` | None (public read) | `gamma-api.polymarket.com` + `clob.polymarket.com`, returns date+close only (probability 0-1), ticker prefix `POLYMARKET:<slug>` |

All implement `PriceProvider.fetch_daily(ticker) -> PriceSeries` from `data/providers.py:34`.

### TUI Application

| File | Purpose |
|------|---------|
| `src/stonks_cli/tui/app.py` | `StonksApp(App)` — main Textual app, 7-tab layout, keybindings, data refresh worker |
| `src/stonks_cli/tui/styles/app.tcss` | TCSS design system (Bloomberg density + Apple restraint) |
| `src/stonks_cli/tui/screens/dashboard.py` | Watchlist summary, portfolio snapshot, alerts, market movers |
| `src/stonks_cli/tui/screens/watchlist.py` | DataTable with ticker/price/change/signal/sparkline, watchlist switching |
| `src/stonks_cli/tui/screens/detail.py` | Ticker detail: chart (plotext), fundamentals, indicators, news, backtest |
| `src/stonks_cli/tui/screens/portfolio.py` | Holdings table, allocation chart, paper buy/sell |
| `src/stonks_cli/tui/screens/analysis.py` | Ticker input + strategy select + run, results table |
| `src/stonks_cli/tui/screens/alerts.py` | Alerts table, add/delete alerts |
| `src/stonks_cli/tui/screens/settings.py` | Editable AppConfig fields, save to disk |

### TUI Widgets

| File | Widget | Purpose |
|------|--------|---------|
| `src/stonks_cli/tui/widgets/price_card.py` | `PriceCard` | Compact ticker+price+change+sparkline |
| `src/stonks_cli/tui/widgets/sparkline_widget.py` | `SparklineWidget` | Color-coded sparkline wrapping `generate_sparkline()` |
| `src/stonks_cli/tui/widgets/ticker_table.py` | `TickerTable` | Reusable DataTable subclass with standard columns |
| `src/stonks_cli/tui/widgets/chart_widget.py` | `ChartWidget` | Renders plotext charts via `build()` in a Static |
| `src/stonks_cli/tui/widgets/metric_card.py` | `MetricCard` | Label+value display (CAGR, Sharpe, etc.) |

### Tests

| File | Tests |
|------|-------|
| `tests/test_finnhub_provider.py` | Mock HTTP, verify DataFrame shape/columns |
| `tests/test_alpaca_provider.py` | Mock SDK, verify DataFrame shape/columns |
| `tests/test_tiger_provider.py` | Mock SDK, verify DataFrame shape/columns |
| `tests/test_polymarket_provider.py` | Mock HTTP, verify date+close only output |

---

## Modified Files

### `pyproject.toml`

- Add optional dep groups: `tui`, `tiger`, `polymarket`, `finnhub`, `alpaca`, `all`
- Add entry point: `stonks-tui`

### `src/stonks_cli/config.py`

- New model: `ApiKeysConfig` (tiger_id, tiger_account, tiger_private_key_path, finnhub_api_key, alpaca_api_key, alpaca_secret_key, alpaca_paper)
- New model: `TuiConfig` (refresh_interval, theme, default_view)
- Extend `DataConfig.provider` literal: add `"tiger"`, `"finnhub"`, `"alpaca"`, `"polymarket"`
- Add `api_keys: ApiKeysConfig` and `tui: TuiConfig` fields to `AppConfig`

### `src/stonks_cli/pipeline.py`

- Extend `provider_for_config()` (~line 92) with lazy-import branches for `tiger`, `finnhub`, `alpaca`, `polymarket` before default StooqProvider fallback

### `src/stonks_cli/cli.py`

- New `tui` command: launches `StonksApp` with optional `--watchlist` and `--refresh` flags
- Guarded with `ImportError` catch for missing `textual` dep
- `watch` command becomes alias for `tui --view watchlist`

### `src/stonks_cli/tui/watchlist_view.py` (DELETED)

- Removed — replaced entirely by Textual watchlist screen
- `do_watch()` in `commands.py` now launches `StonksApp(default_view="watchlist")` directly

---

## Design System (TCSS Tokens)

| Token | Value | Usage |
|-------|-------|-------|
| Surface | `#1a1a2e` | Deep navy background |
| Positive | `#4ecca3` | Soft teal-green for gains |
| Negative | `#e94560` | Muted coral-red for losses |
| Text primary | `#eaeaea` | Main text |
| Text muted | `#8b8b8b` | Secondary text |
| Tab indicator | underline-style | Active tab |
| Table rows | subtle alternating, no grid lines | Data density |

---

## TUI Keybindings

| Key | Action |
|-----|--------|
| `1`-`7` | Switch tabs (Dashboard/Watchlist/Detail/Portfolio/Analysis/Alerts/Settings) |
| `Ctrl+P` | Command palette |
| `q` | Quit |
| `Enter` (watchlist row) | Open ticker in Detail tab |
| `d` (alerts row) | Delete alert |

---

## API Key Configuration

All keys support env var fallback:

| Config Field | Env Var | Required For |
|-------------|---------|-------------|
| `api_keys.finnhub_api_key` | `FINNHUB_API_KEY` | FinnhubProvider |
| `api_keys.alpaca_api_key` | `ALPACA_API_KEY` | AlpacaProvider |
| `api_keys.alpaca_secret_key` | `ALPACA_SECRET_KEY` | AlpacaProvider |
| `api_keys.alpaca_paper` | — | AlpacaProvider (default: true) |
| `api_keys.tiger_id` | — | TigerProvider |
| `api_keys.tiger_account` | — | TigerProvider |
| `api_keys.tiger_private_key_path` | — | TigerProvider |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| plotext `build()` API compat | Fallback: `io.StringIO` stdout capture; pin plotext version |
| Textual API churn | Pin `textual>=0.89,<1.0` |
| Tiger RSA auth complexity | Clear config example + env var override; skip in CI |
| Polymarket non-OHLCV shape | Already handled — strategies return `NO_DATA` gracefully |
| API key security | Env var fallback for all keys, `.gitignore` config dir |

---

## Existing Code Reused (Not Modified)

| What | File | Function/Class |
|------|------|----------------|
| PriceProvider base | `data/providers.py:34` | `class PriceProvider` |
| PriceSeries dataclass | `data/providers.py:28` | `class PriceSeries` |
| Quick analysis | `commands.py:36` | `_fetch_quick_single()` |
| QuickResult model | `commands.py:27` | `class QuickResult` |
| Sparkline generation | `formatting/sparkline.py` | `generate_sparkline()` |
| Portfolio ops | `portfolio/storage.py` | `load_portfolio()` |
| Alert ops | `alerts/storage.py` | `load_alerts()` |
| Indicators | `analysis/indicators.py` | SMA, RSI, MACD, etc. |
| Backtest | `analysis/backtest.py` | `walk_forward_backtest()` |
| Fundamentals | `data/fundamentals.py` | `fetch_fundamentals_yahoo()` |
| News | `data/news.py` | news fetching |
| Cache helpers | `data/cache.py` | `load_cached_text()`, `save_cached_text()` |
