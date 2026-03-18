from __future__ import annotations

import io
import sys

from textual.widgets import Static


class ChartWidget(Static):
    """Renders plotext charts via build() in a Static widget."""
    DEFAULT_CSS = """
    ChartWidget {
        height: auto;
        min-height: 15;
    }
    """
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._chart_text = ""

    def render(self) -> str:
        return self._chart_text or "no chart data"

    def plot_prices(self, prices, title="", width=60, height=15):
        """Render a price chart using plotext."""
        try:
            import plotext as plt
            plt.clear_figure()
            plt.plot(prices, marker="braille")
            plt.title(title)
            plt.plotsize(width, height)
            plt.theme("dark")
            self._chart_text = plt.build()
        except Exception:
            old_stdout = sys.stdout
            try:
                import plotext as plt
                sys.stdout = buf = io.StringIO()
                plt.clear_figure()
                plt.plot(prices, marker="braille")
                plt.title(title)
                plt.plotsize(width, height)
                plt.show()
                self._chart_text = buf.getvalue()
            except Exception as e:
                self._chart_text = f"chart error: {e}"
            finally:
                sys.stdout = old_stdout
        self.refresh()
