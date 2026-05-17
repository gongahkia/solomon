# Equity Archive

Status: archived from the active product surface on 2026-05-17.

The old equity-analysis, report-generation, stock-data provider, charting, and generic stock-MCP work is no longer an active WhaleMirror product surface. The code may remain temporarily as migration reference while Phase 1 replaces it with venue-neutral WhaleMirror primitives, but root CLI help, README quickstart paths, package extras, and MCP examples must not advertise it.

## Archived Surfaces

- `src/stonks_cli/analysis/`
- `src/stonks_cli/charts/`
- `src/stonks_cli/pipeline.py`
- Equity-first CLI commands such as `analyze`, `backtest`, `bench`, `data`, `report`, `history`, `signals`, portfolio paper trading, and stock research notes
- Equity provider adapters and optional extras for yfinance, Stooq, Tiger, Finnhub, Alpaca data-only, and Akshare
- Generic stock MCP examples and stock-data MCP framing

## Active Direction

The visible CLI surface should point users at WhaleMirror, Hyperliquid dry-run/paper workflows, venue-neutral models, decision ledgers, and fixture-backed replay. Any future provider work should be added as a WhaleMirror venue adapter with explicit legal, custody, funding, slippage, and audit constraints.
