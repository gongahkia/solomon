from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Select, Static

ALERT_TYPES = [
    ("price_above", "price_above"),
    ("price_below", "price_below"),
    ("rsi_above", "rsi_above"),
    ("rsi_below", "rsi_below"),
    ("golden_cross", "golden_cross"),
    ("death_cross", "death_cross"),
    ("volume_spike", "volume_spike"),
    ("new_high_52w", "new_high_52w"),
    ("new_low_52w", "new_low_52w"),
]

class AlertsScreen(Widget):
    DEFAULT_CLASSES = "screen-widget"
    BINDINGS = [Binding("d", "delete_alert", "Delete")]
    def compose(self) -> ComposeResult:
        with Vertical():
            yield DataTable(id="al-table")
            with Horizontal():
                yield Input(placeholder="ticker", id="al-ticker")
                yield Select(ALERT_TYPES, id="al-type", prompt="type")
                yield Input(placeholder="threshold", id="al-threshold")
                yield Button("Add", id="al-add")
            yield Static("", id="al-status")

    def on_mount(self) -> None:
        table = self.query_one("#al-table", DataTable)
        table.add_columns("ID", "Ticker", "Type", "Threshold", "Enabled", "Triggered")
        table.cursor_type = "row"
        self.refresh_data()

    def on_button_pressed(self, event) -> None:
        if event.button.id == "al-add":
            self._add_alert()

    def _add_alert(self) -> None:
        from stonks_cli.alerts.models import Alert
        from stonks_cli.alerts.storage import save_alert
        ticker = self.query_one("#al-ticker", Input).value.strip()
        sel = self.query_one("#al-type", Select)
        cond = sel.value if sel.value != Select.BLANK else ""
        threshold_str = self.query_one("#al-threshold", Input).value.strip()
        if not ticker or not cond or not threshold_str:
            self.query_one("#al-status").update("fill all fields")
            return
        try:
            threshold = float(threshold_str)
        except ValueError:
            self.query_one("#al-status").update("invalid threshold")
            return
        alert = Alert(ticker=ticker.upper(), condition_type=cond, threshold=threshold)
        save_alert(alert)
        self.query_one("#al-status").update(f"added alert: {ticker} {cond} @ {threshold}")
        self._load_alerts()

    def action_delete_alert(self) -> None:
        table = self.query_one("#al-table", DataTable)
        if table.cursor_row is not None:
            try:
                row_data = table.get_row_at(table.cursor_row)
                alert_id_short = row_data[0]
                from stonks_cli.alerts.storage import delete_alert, load_alerts
                alerts = load_alerts()
                for a in alerts:
                    if a.id.startswith(alert_id_short):
                        if delete_alert(a.id):
                            self.query_one("#al-status").update(f"deleted alert {a.id[:8]}...")
                            self._load_alerts()
                            return
            except Exception as e:
                self.query_one("#al-status").update(f"error: {e}")

    def refresh_data(self) -> None:
        self._load_alerts()

    def _load_alerts(self) -> None:
        from stonks_cli.alerts.storage import load_alerts
        alerts = load_alerts()
        table = self.query_one("#al-table", DataTable)
        table.clear()
        for a in alerts:
            triggered = a.triggered_at.strftime("%Y-%m-%d %H:%M") if a.triggered_at else "-"
            table.add_row(a.id[:8], a.ticker, a.condition_type, f"{a.threshold}", "yes" if a.enabled else "no", triggered, key=a.id)
