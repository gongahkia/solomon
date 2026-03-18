from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from stonks_cli.config import load_config
from stonks_cli.pipeline import select_strategy


class StonksApp(App):
    CSS_PATH = "styles/app.tcss"
    TITLE = "stonks"
    BINDINGS = [
        Binding("1", "switch_tab('dashboard')", "Dashboard", show=True),
        Binding("2", "switch_tab('watchlist')", "Watchlist", show=True),
        Binding("3", "switch_tab('detail')", "Detail", show=True),
        Binding("4", "switch_tab('portfolio')", "Portfolio", show=True),
        Binding("5", "switch_tab('analysis')", "Analysis", show=True),
        Binding("6", "switch_tab('alerts')", "Alerts", show=True),
        Binding("7", "switch_tab('settings')", "Settings", show=True),
        Binding("q", "quit", "Quit", show=True),
    ]

    def __init__(self, watchlist_name=None, refresh_interval=60, default_view="dashboard"):
        super().__init__()
        self.cfg = load_config()
        self.strategy_fn = select_strategy(self.cfg)
        self.watchlist_name = watchlist_name
        self.refresh_interval = refresh_interval or self.cfg.tui.refresh_interval
        self.default_view = default_view
        self.detail_ticker = None # set when navigating from watchlist

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("Dashboard", id="dashboard"):
                from stonks_cli.tui.screens.dashboard import DashboardScreen
                yield DashboardScreen(id="dashboard-screen")
            with TabPane("Watchlist", id="watchlist"):
                from stonks_cli.tui.screens.watchlist import WatchlistScreen
                yield WatchlistScreen(id="watchlist-screen")
            with TabPane("Detail", id="detail"):
                from stonks_cli.tui.screens.detail import DetailScreen
                yield DetailScreen(id="detail-screen")
            with TabPane("Portfolio", id="portfolio"):
                from stonks_cli.tui.screens.portfolio import PortfolioScreen
                yield PortfolioScreen(id="portfolio-screen")
            with TabPane("Analysis", id="analysis"):
                from stonks_cli.tui.screens.analysis import AnalysisScreen
                yield AnalysisScreen(id="analysis-screen")
            with TabPane("Alerts", id="alerts"):
                from stonks_cli.tui.screens.alerts import AlertsScreen
                yield AlertsScreen(id="alerts-screen")
            with TabPane("Settings", id="settings"):
                from stonks_cli.tui.screens.settings import SettingsScreen
                yield SettingsScreen(id="settings-screen")
        yield Footer()

    def on_mount(self) -> None:
        if self.cfg.tui.theme == "light":
            self.theme = "textual-light"
        else:
            self.theme = "textual-dark"
        if self.default_view != "dashboard":
            self.query_one(TabbedContent).active = self.default_view
        self.set_interval(self.refresh_interval, self.action_refresh_data)

    def action_switch_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_refresh_data(self) -> None:
        for screen_widget in self.query(".screen-widget"): # notify all screens to refresh
            if hasattr(screen_widget, "refresh_data"):
                screen_widget.refresh_data()

    def set_detail_ticker(self, ticker: str) -> None:
        self.detail_ticker = ticker
        self.query_one(TabbedContent).active = "detail"
        detail = self.query_one("#detail-screen")
        if hasattr(detail, "load_ticker"):
            detail.load_ticker(ticker)

def main():
    StonksApp().run()

if __name__ == "__main__":
    main()
