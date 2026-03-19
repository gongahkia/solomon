from __future__ import annotations

from textual.widgets import Static

from stonks_cli.formatting.sparkline import generate_sparkline


class SparklineWidget(Static):
    """Color-coded sparkline widget."""

    def __init__(self, prices=None, width=20, **kwargs):
        super().__init__(**kwargs)
        self.prices = prices or []
        self.width = width

    def render(self) -> str:
        if not self.prices:
            return ""
        spark = generate_sparkline(self.prices, width=self.width)
        if len(self.prices) >= 2 and self.prices[-1] >= self.prices[0]:
            return f"[#4ecca3]{spark}[/]"
        return f"[#e94560]{spark}[/]"

    def update_prices(self, prices):
        self.prices = prices or []
        self.refresh()
