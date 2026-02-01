from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from stonks_cli.commands import QuickResult, _fetch_quick_single
from stonks_cli.config import load_config
from stonks_cli.formatting.sparkline import generate_sparkline
from stonks_cli.pipeline import select_strategy


class WatchlistTUI:
    """Terminal UI for watching a list of tickers with live updates."""

    def __init__(
        self,
        watchlist_name: str | None = None,
        refresh_interval: int = 60,
    ):
        self.cfg = load_config()
        self.strategy_fn = select_strategy(self.cfg)
        self.refresh_interval = refresh_interval
        self.running = True
        self.selected_row = 0
        self.in_detail_view = False
        self.detail_ticker: str | None = None
        self.last_refresh: datetime | None = None
        self.results: list[QuickResult] = []
        self.sort_mode = "ticker"  # ticker, change, confidence

        # Get available watchlists
        self.watchlists = list((self.cfg.watchlists or {}).keys())
        if not self.watchlists:
            self.watchlists = ["default"]

        # Set current watchlist
        if watchlist_name and watchlist_name in self.watchlists:
            self.current_watchlist = watchlist_name
        elif self.watchlists:
            self.current_watchlist = self.watchlists[0]
        else:
            self.current_watchlist = "default"

        self.watchlist_index = (
            self.watchlists.index(self.current_watchlist) if self.current_watchlist in self.watchlists else 0
        )

    def get_tickers(self) -> list[str]:
        """Get tickers for current watchlist."""
        watchlists = self.cfg.watchlists or {}
        tickers = watchlists.get(self.current_watchlist, [])
        if not tickers and self.cfg.tickers:
            return list(self.cfg.tickers)
        return list(tickers) if tickers else []

    def fetch_data(self) -> list[QuickResult]:
        """Fetch data for all tickers in current watchlist."""
        tickers = self.get_tickers()
        if not tickers:
            return []

        results: list[QuickResult] = []
        max_workers = min(self.cfg.data.concurrency_limit, max(1, len(tickers)))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(_fetch_quick_single, t, self.cfg, self.strategy_fn): t for t in tickers}
            for fut in as_completed(futures):
                results.append(fut.result())

        # Sort results
        results = self.sort_results(results)
        self.last_refresh = datetime.now()
        return results

    def sort_results(self, results: list[QuickResult]) -> list[QuickResult]:
        """Sort results based on current sort mode."""
        if self.sort_mode == "ticker":
            return sorted(results, key=lambda r: r.ticker)
        elif self.sort_mode == "change":
            return sorted(results, key=lambda r: r.change_pct or 0, reverse=True)
        elif self.sort_mode == "confidence":
            return sorted(results, key=lambda r: r.confidence, reverse=True)
        return results

    def cycle_sort(self) -> None:
        """Cycle through sort modes."""
        modes = ["ticker", "change", "confidence"]
        idx = modes.index(self.sort_mode)
        self.sort_mode = modes[(idx + 1) % len(modes)]
        self.results = self.sort_results(self.results)

    def cycle_watchlist(self) -> None:
        """Cycle to next watchlist."""
        if not self.watchlists:
            return
        self.watchlist_index = (self.watchlist_index + 1) % len(self.watchlists)
        self.current_watchlist = self.watchlists[self.watchlist_index]
        self.selected_row = 0
        self.results = self.fetch_data()

    def render_table(self) -> Table:
        """Render the watchlist table."""
        table = Table(title=f"Watchlist: {self.current_watchlist}")
        table.add_column("", style="dim", width=3)  # Selection indicator
        table.add_column("Ticker", style="cyan")
        table.add_column("Price", justify="right")
        table.add_column("Change%", justify="right")
        table.add_column("Signal", style="bold")
        table.add_column("Confidence", justify="right")
        table.add_column("Sparkline")

        for i, result in enumerate(self.results):
            # Selection indicator
            indicator = ">" if i == self.selected_row else " "

            # Price
            price_str = f"${result.price:.2f}" if result.price else "N/A"

            # Change percentage with color
            if result.change_pct is not None:
                sign = "+" if result.change_pct >= 0 else ""
                color = "green" if result.change_pct >= 0 else "red"
                change_str = f"[{color}]{sign}{result.change_pct:.2f}%[/{color}]"
            else:
                change_str = "N/A"

            # Action with color
            action_colors = {
                "BUY_DCA": "green",
                "HOLD_DCA": "green",
                "HOLD": "yellow",
                "HOLD_WAIT": "yellow",
                "WATCH_REVERSAL": "yellow",
                "AVOID_OR_HEDGE": "red",
                "REDUCE_EXPOSURE": "red",
                "NO_DATA": "red",
                "INSUFFICIENT_HISTORY": "yellow",
            }
            color = action_colors.get(result.action, "white")
            action_str = f"[{color}]{result.action}[/{color}]"

            # Confidence
            conf_str = f"{result.confidence:.2f}"

            # Sparkline
            sparkline = generate_sparkline(result.prices, width=15) if result.prices else ""

            table.add_row(indicator, result.ticker, price_str, change_str, action_str, conf_str, sparkline)

        return table

    def render_detail_view(self, ticker: str) -> Panel:
        """Render detailed view for a single ticker."""
        result = next((r for r in self.results if r.ticker == ticker), None)
        if not result:
            return Panel("No data", title=ticker)

        lines = []

        # Price and change
        price_str = f"${result.price:.2f}" if result.price else "N/A"
        if result.change_pct is not None:
            sign = "+" if result.change_pct >= 0 else ""
            change_str = f"{sign}{result.change_pct:.2f}%"
        else:
            change_str = "N/A"
        lines.append(f"Price: {price_str} ({change_str})")
        lines.append("")

        # Signal
        lines.append(f"Signal: {result.action}")
        lines.append(f"Confidence: {result.confidence:.2f}")
        lines.append("")

        # Sparkline
        if result.prices:
            sparkline = generate_sparkline(result.prices, width=40)
            lines.append(f"Last 20 days: {sparkline}")

        content = "\n".join(lines)
        return Panel(content, title=f"{ticker} Detail View", subtitle="[b]ack to list")

    def render_status_bar(self) -> Text:
        """Render status bar at bottom."""
        refresh_str = self.last_refresh.strftime("%H:%M:%S") if self.last_refresh else "never"
        sort_str = f"sort:{self.sort_mode}"
        text = Text()
        text.append(f" {self.current_watchlist} ", style="reverse")
        text.append(f" | Last refresh: {refresh_str} | {sort_str} | ")
        text.append("[q]", style="bold")
        text.append("uit ")
        text.append("[r]", style="bold")
        text.append("efresh ")
        text.append("[w]", style="bold")
        text.append("atchlist ")
        text.append("[s]", style="bold")
        text.append("ort ")
        text.append("[enter]", style="bold")
        text.append("detail")
        return text

    def render(self) -> Layout:
        """Render the full TUI layout."""
        layout = Layout()

        if self.in_detail_view and self.detail_ticker:
            layout.split_column(
                Layout(self.render_detail_view(self.detail_ticker), name="main"),
                Layout(self.render_status_bar(), name="status", size=1),
            )
        else:
            layout.split_column(
                Layout(self.render_table(), name="main"),
                Layout(self.render_status_bar(), name="status", size=1),
            )

        return layout

    def handle_key(self, key: str) -> None:
        """Handle keyboard input."""
        if self.in_detail_view:
            if key == "b" or key == "escape":
                self.in_detail_view = False
                self.detail_ticker = None
            return

        if key == "q":
            self.running = False
        elif key == "r":
            self.results = self.fetch_data()
        elif key == "w":
            self.cycle_watchlist()
        elif key == "s":
            self.cycle_sort()
        elif key in ("j", "down"):
            if self.results:
                self.selected_row = min(self.selected_row + 1, len(self.results) - 1)
        elif key in ("k", "up"):
            self.selected_row = max(self.selected_row - 1, 0)
        elif key == "enter":
            if self.results and 0 <= self.selected_row < len(self.results):
                self.in_detail_view = True
                self.detail_ticker = self.results[self.selected_row].ticker

    def run(self) -> None:
        """Run the TUI main loop."""
        console = Console()

        # Initial fetch
        self.results = self.fetch_data()

        # Check if we can use keyboard input
        try:
            import select

            has_select = True
        except ImportError:
            has_select = False

        with Live(self.render(), console=console, refresh_per_second=4, screen=True) as live:
            last_refresh_time = time.time()

            while self.running:
                # Auto-refresh
                if time.time() - last_refresh_time >= self.refresh_interval:
                    self.results = self.fetch_data()
                    last_refresh_time = time.time()

                live.update(self.render())

                # Non-blocking key input (Unix only)
                if has_select and sys.stdin.isatty():
                    import termios
                    import tty

                    old_settings = termios.tcgetattr(sys.stdin)
                    try:
                        tty.setcbreak(sys.stdin.fileno())
                        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
                        if rlist:
                            key = sys.stdin.read(1)
                            if key == "\x1b":  # Escape sequence
                                key2 = sys.stdin.read(2)
                                if key2 == "[A":
                                    key = "up"
                                elif key2 == "[B":
                                    key = "down"
                                else:
                                    key = "escape"
                            elif key == "\r" or key == "\n":
                                key = "enter"
                            self.handle_key(key)
                    finally:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                else:
                    time.sleep(0.1)
