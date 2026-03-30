# TODO - 30 March 2026

## Remaining Unfinished Work

- [ ] Implement `do_earnings()` calendar mode (no `--ticker`) so it returns a real upcoming earnings calendar instead of the current placeholder message.
- [ ] Remove/replace remaining silent `except ...: pass` paths in data collectors:
  - `src/stonks_cli/data/earnings.py`
  - `src/stonks_cli/data/news.py`
  - `src/stonks_cli/data/dividends.py`
  - `src/stonks_cli/data/sec_edgar.py`
  - `src/stonks_cli/data/fundamentals.py`
- [ ] Replace remaining silent `pass` paths in TUI screens with tracked logs:
  - `src/stonks_cli/tui/screens/watchlist.py`
  - `src/stonks_cli/tui/screens/settings.py`
  - `src/stonks_cli/tui/screens/dashboard.py`
  - `src/stonks_cli/tui/screens/analysis.py`
  - `src/stonks_cli/tui/screens/portfolio.py`
- [ ] Replace remaining silent `pass` paths in portfolio runtime logic:
  - `src/stonks_cli/portfolio/paper.py`
- [ ] Add direct tests for new surfaces (currently command-layer coverage exists):
  - CLI-level test for `stonks-cli snapshot`
  - MCP-level test for `get_market_snapshot`

## Notes

- `PriceProvider.fetch_daily()` raising `NotImplementedError` is intentional abstract-interface behavior, not a stub bug.
- Core CI parity currently passes after the latest upgrade; this TODO list tracks remaining completeness work to remove outstanding silent-failure pockets and placeholder behavior.
