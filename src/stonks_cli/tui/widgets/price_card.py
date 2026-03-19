from __future__ import annotations

from textual.widgets import Static


class PriceCard(Static):
    """Compact ticker+price+change+sparkline card."""

    DEFAULT_CSS = """
    PriceCard {
        background: #16213e;
        border: tall #0f3460;
        padding: 1 2;
        height: auto;
        min-width: 30;
    }
    """

    def __init__(self, ticker="", price=0.0, change_pct=None, sparkline="", **kwargs):
        super().__init__(**kwargs)
        self.ticker = ticker
        self.price = price
        self.change_pct = change_pct
        self.sparkline = sparkline

    def render(self) -> str:
        price_str = f"${self.price:.2f}" if self.price else "N/A"
        if self.change_pct is not None:
            sign = "+" if self.change_pct >= 0 else ""
            change_str = f"{sign}{self.change_pct:.2f}%"
        else:
            change_str = ""
        return f"{self.ticker}  {price_str}  {change_str}\n{self.sparkline}"

    def update_data(self, ticker, price, change_pct, sparkline):
        self.ticker = ticker
        self.price = price
        self.change_pct = change_pct
        self.sparkline = sparkline
        self.refresh()
