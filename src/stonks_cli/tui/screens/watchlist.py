from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Select

from stonks_cli.logging_utils import log_suppressed_exception


class WatchlistScreen(Vertical):
    DEFAULT_CLASSES = "screen-widget"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._results = []

    def compose(self) -> ComposeResult:
        yield Select([], id="wl-select", prompt="select watchlist")
        yield DataTable(id="wl-table")

    def on_mount(self) -> None:
        table = self.query_one("#wl-table", DataTable)
        table.add_columns("Ticker", "Price", "Change%", "Signal", "Confidence", "Sparkline")
        table.cursor_type = "row"
        # populate watchlist selector
        from stonks_cli.config import load_config

        cfg = load_config()
        wl = cfg.watchlists or {}
        options = [(name, name) for name in sorted(wl.keys())]
        if options:
            sel = self.query_one("#wl-select", Select)
            sel.set_options(options)
            sel.value = options[0][1]
        self.refresh_data()

    def on_select_changed(self, event) -> None:
        self.refresh_data()

    def on_data_table_row_selected(self, event) -> None:
        # navigate to detail view
        if event.row_key and hasattr(self.app, "set_detail_ticker"):
            self.app.set_detail_ticker(str(event.row_key.value))

    @work(thread=True)
    def refresh_data(self) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from stonks_cli.commands import _fetch_quick_single
        from stonks_cli.config import load_config
        from stonks_cli.formatting.sparkline import generate_sparkline
        from stonks_cli.pipeline import select_strategy

        cfg = load_config()
        strategy_fn = select_strategy(cfg)
        sel = self.query_one("#wl-select", Select)
        wl_name = sel.value if sel.value != Select.BLANK else None
        wl = cfg.watchlists or {}
        tickers = list(wl.get(wl_name, [])) if wl_name else list(cfg.tickers)
        if not tickers:
            return
        results = []
        max_workers = min(cfg.data.concurrency_limit, max(1, len(tickers)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_fetch_quick_single, t, cfg, strategy_fn): t for t in tickers}
            for fut in as_completed(futs):
                try:
                    results.append(fut.result())
                except Exception as e:
                    log_suppressed_exception(
                        context="tui.watchlist.refresh_data.fetch_ticker",
                        error=e,
                        ticker=futs.get(fut),
                    )
        results.sort(key=lambda r: r.ticker)
        self._results = results

        def _update():
            table = self.query_one("#wl-table", DataTable)
            table.clear()
            for r in results:
                price_str = f"${r.price:.2f}" if r.price else "N/A"
                if r.change_pct is not None:
                    sign = "+" if r.change_pct >= 0 else ""
                    change_str = f"{sign}{r.change_pct:.2f}%"
                else:
                    change_str = "N/A"
                spark = generate_sparkline(r.prices, width=15) if r.prices else ""
                table.add_row(r.ticker, price_str, change_str, r.action, f"{r.confidence:.2f}", spark, key=r.ticker)

        self.app.call_from_thread(_update)
