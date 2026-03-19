from __future__ import annotations

from textual.widgets import Static


class MetricCard(Static):
    """Label+value metric display (CAGR, Sharpe, etc.)."""

    DEFAULT_CSS = """
    MetricCard {
        background: #16213e;
        border: tall #0f3460;
        padding: 1 2;
        height: auto;
        min-width: 20;
    }
    """

    def __init__(self, label="", value="", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self.value = value

    def render(self) -> str:
        return f"[#8b8b8b]{self.label}[/]\n[bold #eaeaea]{self.value}[/]"

    def update_metric(self, label=None, value=None):
        if label is not None:
            self.label = label
        if value is not None:
            self.value = value
        self.refresh()
