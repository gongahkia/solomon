from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, LoadingIndicator, Select, Static

STRATEGIES = [
    ("basic_trend_rsi", "basic_trend_rsi"),
    ("sma_cross", "sma_cross"),
    ("mean_reversion_bb_rsi", "mean_reversion_bb_rsi"),
]

class AnalysisScreen(Widget):
    DEFAULT_CLASSES = "screen-widget"
    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                yield Input(placeholder="tickers (comma-separated)", id="an-tickers")
                yield Select(STRATEGIES, id="an-strategy", prompt="strategy")
                yield Button("Run", id="an-run")
            yield LoadingIndicator(id="an-loading")
            yield DataTable(id="an-results")
            yield Static("", id="an-status")

    def on_mount(self) -> None:
        table = self.query_one("#an-results", DataTable)
        table.add_columns("Ticker", "Signal", "Confidence", "CAGR", "Sharpe", "Max DD", "Win Rate")
        self.query_one("#an-loading").display = False

    def on_button_pressed(self, event) -> None:
        if event.button.id == "an-run":
            self._run_analysis()

    @work(thread=True)
    def _run_analysis(self) -> None:
        self.app.call_from_thread(setattr, self.query_one("#an-loading"), "display", True)
        self.app.call_from_thread(self.query_one("#an-status").update, "running...")
        try:
            import io

            from rich.console import Console

            from stonks_cli.config import load_config
            from stonks_cli.pipeline import compute_results
            tickers_str = self.query_one("#an-tickers", Input).value.strip()
            sel = self.query_one("#an-strategy", Select)
            strategy = sel.value if sel.value != Select.BLANK else "basic_trend_rsi"
            if not tickers_str:
                self.app.call_from_thread(self.query_one("#an-status").update, "enter tickers")
                self.app.call_from_thread(setattr, self.query_one("#an-loading"), "display", False)
                return
            tickers = [t.strip() for t in tickers_str.split(",") if t.strip()]
            cfg = load_config()
            cfg = cfg.model_copy(update={"tickers": tickers, "strategy": strategy})
            console = Console(file=io.StringIO())
            results, portfolio_metrics = compute_results(cfg, console)
            def _update():
                table = self.query_one("#an-results", DataTable)
                table.clear()
                for r in results:
                    cagr = f"{r.backtest.cagr:.4f}" if r.backtest and r.backtest.cagr is not None else "N/A"
                    sharpe = f"{r.backtest.sharpe:.4f}" if r.backtest and r.backtest.sharpe is not None else "N/A"
                    max_dd = f"{r.backtest.max_drawdown:.4f}" if r.backtest and r.backtest.max_drawdown is not None else "N/A"
                    win_rate = f"{r.backtest.win_rate:.4f}" if r.backtest and r.backtest.win_rate is not None else "N/A"
                    table.add_row(r.ticker, r.recommendation.action, f"{r.recommendation.confidence:.2f}", cagr, sharpe, max_dd, win_rate)
                self.query_one("#an-status").update(f"done — {len(results)} tickers analyzed")
                self.query_one("#an-loading").display = False
            self.app.call_from_thread(_update)
        except Exception as e:
            self.app.call_from_thread(self.query_one("#an-status").update, f"error: {e}")
            self.app.call_from_thread(setattr, self.query_one("#an-loading"), "display", False)

    def refresh_data(self) -> None:
        pass
