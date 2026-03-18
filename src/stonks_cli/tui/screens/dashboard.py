from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static
from textual import work


class DashboardScreen(Static):
    DEFAULT_CLASSES = "screen-widget"
    def compose(self) -> ComposeResult:
        with Container(id="dashboard-grid"):
            yield Static("Loading...", id="dash-watchlist", classes="dashboard-panel")
            yield Static("Loading...", id="dash-portfolio", classes="dashboard-panel")
            yield Static("Loading...", id="dash-alerts", classes="dashboard-panel")
            yield Static("Loading...", id="dash-movers", classes="dashboard-panel")

    def on_mount(self) -> None:
        self.refresh_data()

    @work(thread=True)
    def refresh_data(self) -> None:
        # watchlist summary
        try:
            from stonks_cli.commands import _fetch_quick_single
            from stonks_cli.config import load_config
            from stonks_cli.pipeline import select_strategy
            cfg = load_config()
            strategy_fn = select_strategy(cfg)
            tickers = cfg.tickers[:10]
            wl = cfg.watchlists or {}
            if wl:
                first_wl = list(wl.values())[0]
                if first_wl:
                    tickers = first_wl[:10]
            results = []
            for t in tickers[:5]:
                try:
                    results.append(_fetch_quick_single(t, cfg, strategy_fn))
                except Exception:
                    pass
            results.sort(key=lambda r: abs(r.change_pct or 0), reverse=True)
            lines = ["[bold]Top Movers[/]\n"]
            for r in results[:5]:
                pct = f"{r.change_pct:+.2f}%" if r.change_pct else "N/A"
                price = f"${r.price:.2f}" if r.price else "N/A"
                lines.append(f"  {r.ticker:<12} {price:>10}  {pct:>8}")
            self.app.call_from_thread(self.query_one("#dash-watchlist").update, "\n".join(lines) or "no data")
        except Exception as e:
            self.app.call_from_thread(self.query_one("#dash-watchlist").update, f"error: {e}")
        # portfolio snapshot
        try:
            from stonks_cli.portfolio.storage import load_portfolio
            portfolio = load_portfolio()
            if portfolio.positions:
                total_cost = sum(p.shares * p.cost_basis_per_share for p in portfolio.positions)
                count = len(portfolio.positions)
                text = f"[bold]Portfolio[/]\n\n  Positions: {count}\n  Total cost: ${total_cost:,.2f}\n  Cash: ${portfolio.cash_balance:,.2f}"
            else:
                text = "[bold]Portfolio[/]\n\n  No positions"
            self.app.call_from_thread(self.query_one("#dash-portfolio").update, text)
        except Exception as e:
            self.app.call_from_thread(self.query_one("#dash-portfolio").update, f"error: {e}")
        # alerts
        try:
            from stonks_cli.alerts.storage import load_alerts
            alerts = load_alerts()
            triggered = [a for a in alerts if a.triggered_at]
            lines = ["[bold]Recent Alerts[/]\n"]
            if triggered:
                for a in triggered[-5:]:
                    lines.append(f"  {a.ticker} {a.condition_type} @ {a.threshold}")
            else:
                lines.append("  no triggered alerts")
            self.app.call_from_thread(self.query_one("#dash-alerts").update, "\n".join(lines))
        except Exception as e:
            self.app.call_from_thread(self.query_one("#dash-alerts").update, f"error: {e}")
        # movers placeholder
        self.app.call_from_thread(self.query_one("#dash-movers").update, "[bold]Market Movers[/]\n\n  run analysis to populate")
