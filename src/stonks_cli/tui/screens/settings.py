from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, Static


class SettingsScreen(Widget):
    DEFAULT_CLASSES = "screen-widget"
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[bold]Settings[/]", classes="panel-title")
            with Horizontal():
                yield Label("Provider:")
                yield Select([
                    ("stooq", "stooq"), ("yfinance", "yfinance"), ("csv", "csv"),
                    ("finnhub", "finnhub"), ("alpaca", "alpaca"), ("tiger", "tiger"), ("polymarket", "polymarket"),
                ], id="set-provider", prompt="provider")
            with Horizontal():
                yield Label("Strategy:")
                yield Select([
                    ("basic_trend_rsi", "basic_trend_rsi"),
                    ("sma_cross", "sma_cross"),
                    ("mean_reversion_bb_rsi", "mean_reversion_bb_rsi"),
                ], id="set-strategy", prompt="strategy")
            with Horizontal():
                yield Label("Cache TTL (s):")
                yield Input(placeholder="3600", id="set-cache-ttl")
            with Horizontal():
                yield Label("TUI Refresh (s):")
                yield Input(placeholder="60", id="set-tui-refresh")
            with Horizontal():
                yield Label("Theme:")
                yield Select([("dark", "dark"), ("light", "light")], id="set-theme", prompt="theme")
            with Horizontal():
                yield Label("Finnhub Key:")
                yield Input(placeholder="api key", id="set-finnhub-key", password=True)
            with Horizontal():
                yield Label("Alpaca Key:")
                yield Input(placeholder="api key", id="set-alpaca-key", password=True)
            with Horizontal():
                yield Label("Alpaca Secret:")
                yield Input(placeholder="secret", id="set-alpaca-secret", password=True)
            yield Button("Save", id="set-save")
            yield Static("", id="set-status")

    def on_mount(self) -> None:
        from stonks_cli.config import load_config
        cfg = load_config()
        try:
            self.query_one("#set-provider", Select).value = cfg.data.provider
            self.query_one("#set-strategy", Select).value = cfg.strategy
            self.query_one("#set-cache-ttl", Input).value = str(cfg.data.cache_ttl_seconds)
            self.query_one("#set-tui-refresh", Input).value = str(cfg.tui.refresh_interval)
            self.query_one("#set-theme", Select).value = cfg.tui.theme
            if cfg.api_keys.finnhub_api_key:
                self.query_one("#set-finnhub-key", Input).value = cfg.api_keys.finnhub_api_key
            if cfg.api_keys.alpaca_api_key:
                self.query_one("#set-alpaca-key", Input).value = cfg.api_keys.alpaca_api_key
            if cfg.api_keys.alpaca_secret_key:
                self.query_one("#set-alpaca-secret", Input).value = cfg.api_keys.alpaca_secret_key
        except Exception:
            pass

    def on_button_pressed(self, event) -> None:
        if event.button.id == "set-save":
            self._save()

    def _save(self) -> None:
        from stonks_cli.config import load_config, save_config
        cfg = load_config()
        try:
            provider_sel = self.query_one("#set-provider", Select)
            provider = provider_sel.value if provider_sel.value != Select.BLANK else cfg.data.provider
            strategy_sel = self.query_one("#set-strategy", Select)
            strategy = strategy_sel.value if strategy_sel.value != Select.BLANK else cfg.strategy
            cache_ttl = int(self.query_one("#set-cache-ttl", Input).value or cfg.data.cache_ttl_seconds)
            tui_refresh = int(self.query_one("#set-tui-refresh", Input).value or cfg.tui.refresh_interval)
            theme_sel = self.query_one("#set-theme", Select)
            theme = theme_sel.value if theme_sel.value != Select.BLANK else cfg.tui.theme
            finnhub_key = self.query_one("#set-finnhub-key", Input).value or None
            alpaca_key = self.query_one("#set-alpaca-key", Input).value or None
            alpaca_secret = self.query_one("#set-alpaca-secret", Input).value or None
            data = cfg.data.model_copy(update={"provider": provider, "cache_ttl_seconds": cache_ttl})
            tui_cfg = cfg.tui.model_copy(update={"refresh_interval": tui_refresh, "theme": theme})
            api_keys = cfg.api_keys.model_copy(update={"finnhub_api_key": finnhub_key, "alpaca_api_key": alpaca_key, "alpaca_secret_key": alpaca_secret})
            cfg = cfg.model_copy(update={"data": data, "strategy": strategy, "tui": tui_cfg, "api_keys": api_keys})
            path = save_config(cfg)
            self.query_one("#set-status").update(f"saved to {path}")
        except Exception as e:
            self.query_one("#set-status").update(f"error: {e}")

    def refresh_data(self) -> None:
        pass
