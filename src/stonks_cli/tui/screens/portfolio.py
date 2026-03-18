from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Static


class PortfolioScreen(Vertical):
    DEFAULT_CLASSES = "screen-widget"
    def compose(self) -> ComposeResult:
        yield DataTable(id="pf-table")
        yield Static("", id="pf-allocation")
        with Horizontal():
            yield Input(placeholder="ticker", id="pf-ticker")
            yield Input(placeholder="shares", id="pf-shares")
            yield Input(placeholder="price", id="pf-price")
            yield Button("Buy", id="pf-buy")
            yield Button("Sell", id="pf-sell")
        yield Static("", id="pf-status")

    def on_mount(self) -> None:
        table = self.query_one("#pf-table", DataTable)
        table.add_columns("Ticker", "Shares", "Cost Basis", "Current", "Value", "P&L", "P&L%")
        self.refresh_data()

    def on_button_pressed(self, event) -> None:
        ticker = self.query_one("#pf-ticker", Input).value.strip()
        shares_str = self.query_one("#pf-shares", Input).value.strip()
        price_str = self.query_one("#pf-price", Input).value.strip()
        if not ticker or not shares_str or not price_str:
            self.query_one("#pf-status").update("fill all fields")
            return
        try:
            shares = float(shares_str)
            price = float(price_str)
        except ValueError:
            self.query_one("#pf-status").update("invalid number")
            return
        if event.button.id == "pf-buy":
            self._do_buy(ticker, shares, price)
        elif event.button.id == "pf-sell":
            self._do_sell(ticker, shares, price)

    @work(thread=True)
    def _do_buy(self, ticker, shares, price):
        try:
            from stonks_cli.portfolio.storage import add_position
            add_position(ticker, shares, price)
            self.app.call_from_thread(self.query_one("#pf-status").update, f"bought {shares} {ticker} @ ${price:.2f}")
            self.app.call_from_thread(self._refresh_sync)
        except Exception as e:
            self.app.call_from_thread(self.query_one("#pf-status").update, f"error: {e}")

    @work(thread=True)
    def _do_sell(self, ticker, shares, price):
        try:
            from stonks_cli.portfolio.storage import remove_position
            result = remove_position(ticker, shares, price)
            gl = result["realized_gain_loss"]
            self.app.call_from_thread(self.query_one("#pf-status").update, f"sold {shares} {ticker} @ ${price:.2f} | P&L: ${gl:+,.2f}")
            self.app.call_from_thread(self._refresh_sync)
        except Exception as e:
            self.app.call_from_thread(self.query_one("#pf-status").update, f"error: {e}")

    @work(thread=True)
    def refresh_data(self) -> None:
        self.app.call_from_thread(self._refresh_sync)

    def _refresh_sync(self) -> None:
        from stonks_cli.portfolio.storage import load_portfolio
        portfolio = load_portfolio()
        table = self.query_one("#pf-table", DataTable)
        table.clear()
        if not portfolio.positions:
            self.query_one("#pf-allocation").update("no positions")
            return
        from stonks_cli.config import load_config
        from stonks_cli.data.providers import normalize_ticker
        from stonks_cli.pipeline import provider_for_config
        cfg = load_config()
        prices = {}
        for pos in portfolio.positions:
            if pos.ticker not in prices:
                try:
                    normalized = normalize_ticker(pos.ticker)
                    provider = provider_for_config(cfg, normalized)
                    series = provider.fetch_daily(normalized)
                    if not series.df.empty and "close" in series.df.columns:
                        prices[pos.ticker] = float(series.df["close"].iloc[-1])
                except Exception:
                    pass
        agg = {}
        for pos in portfolio.positions:
            if pos.ticker not in agg:
                agg[pos.ticker] = {"shares": 0.0, "cost": 0.0}
            agg[pos.ticker]["shares"] += pos.shares
            agg[pos.ticker]["cost"] += pos.shares * pos.cost_basis_per_share
        for ticker, data in sorted(agg.items()):
            shares = data["shares"]
            cost = data["cost"]
            avg_cost = cost / shares if shares else 0
            current = prices.get(ticker, 0)
            value = shares * current
            pnl = value - cost
            pnl_pct = (pnl / cost * 100) if cost else 0
            table.add_row(ticker, f"{shares:.2f}", f"${avg_cost:.2f}", f"${current:.2f}", f"${value:,.2f}", f"${pnl:+,.2f}", f"{pnl_pct:+.2f}%")
        total = sum(agg[t]["shares"] * prices.get(t, 0) for t in agg)
        if total > 0:
            blocks = "Allocation: "
            for ticker in sorted(agg.keys()):
                val = agg[ticker]["shares"] * prices.get(ticker, 0)
                pct = val / total * 100
                bar_len = max(1, int(pct / 5))
                blocks += f" {ticker} {'█' * bar_len} {pct:.0f}%  "
            self.query_one("#pf-allocation").update(blocks)
