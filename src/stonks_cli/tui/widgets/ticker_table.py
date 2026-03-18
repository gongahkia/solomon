from __future__ import annotations

from textual.widgets import DataTable


class TickerTable(DataTable):
    """Reusable DataTable with standard ticker columns."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup_columns(self, columns=None):
        cols = columns or [
            ("Ticker", 10),
            ("Price", 10),
            ("Change%", 10),
            ("Signal", 18),
            ("Confidence", 10),
            ("Sparkline", 20),
        ]
        for name, width in cols:
            self.add_column(name, width=width)

    def load_results(self, results):
        """Load QuickResult list into table."""
        self.clear()
        from stonks_cli.formatting.sparkline import generate_sparkline
        for r in results:
            price_str = f"${r.price:.2f}" if r.price else "N/A"
            if r.change_pct is not None:
                sign = "+" if r.change_pct >= 0 else ""
                change_str = f"{sign}{r.change_pct:.2f}%"
            else:
                change_str = "N/A"
            spark = generate_sparkline(r.prices, width=15) if r.prices else ""
            self.add_row(r.ticker, price_str, change_str, r.action, f"{r.confidence:.2f}", spark, key=r.ticker)
