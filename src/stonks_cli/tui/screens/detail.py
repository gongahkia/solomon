from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static
from textual import work


class DetailScreen(Static):
    DEFAULT_CLASSES = "screen-widget"
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ticker = None

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal():
                yield Input(placeholder="ticker (e.g. AAPL)", id="detail-ticker-input")
            yield Static("enter a ticker or select from watchlist", id="detail-header")
            with Horizontal():
                yield Static("", id="detail-chart", classes="dashboard-panel")
                yield Static("", id="detail-fundamentals", classes="dashboard-panel")
            with Horizontal():
                yield Static("", id="detail-indicators", classes="dashboard-panel")
                yield Static("", id="detail-news", classes="dashboard-panel")
                yield Static("", id="detail-backtest", classes="dashboard-panel")

    def on_input_submitted(self, event) -> None:
        if event.input.id == "detail-ticker-input" and event.value.strip():
            self.load_ticker(event.value.strip())

    def load_ticker(self, ticker: str) -> None:
        self._ticker = ticker
        inp = self.query_one("#detail-ticker-input", Input)
        inp.value = ticker
        self.query_one("#detail-header").update(f"loading {ticker}...")
        self._load_data(ticker)

    @work(thread=True)
    def _load_data(self, ticker: str) -> None:
        from stonks_cli.config import load_config
        from stonks_cli.data.providers import normalize_ticker
        from stonks_cli.pipeline import provider_for_config, select_strategy
        cfg = load_config()
        normalized = normalize_ticker(ticker)
        try:
            provider = provider_for_config(cfg, normalized)
            series = provider.fetch_daily(normalized)
            df = series.df
        except Exception as e:
            self.app.call_from_thread(self.query_one("#detail-header").update, f"error fetching {ticker}: {e}")
            return
        if df.empty or "close" not in df.columns:
            self.app.call_from_thread(self.query_one("#detail-header").update, f"no data for {ticker}")
            return
        last_close = float(df["close"].iloc[-1])
        change_pct = None
        if len(df) >= 2:
            prev = float(df["close"].iloc[-2])
            if prev != 0:
                change_pct = ((last_close - prev) / prev) * 100
        strategy_fn = select_strategy(cfg)
        rec = strategy_fn(df) if len(df) >= cfg.risk.min_history_days else None
        pct_str = f"{change_pct:+.2f}%" if change_pct is not None else ""
        sig_str = f"{rec.action} ({rec.confidence:.2f})" if rec else "INSUFFICIENT_HISTORY"
        header = f"[bold]{normalized}[/]   ${last_close:.2f}   {pct_str}   {sig_str}"
        self.app.call_from_thread(self.query_one("#detail-header").update, header)
        try: # chart
            import plotext as plt
            prices = df["close"].tail(90).tolist()
            plt.clear_figure()
            plt.plot(prices, marker="braille")
            plt.title(f"{normalized} (90d)")
            plt.plotsize(60, 15)
            plt.theme("dark")
            chart_str = plt.build()
        except Exception:
            chart_str = "plotext unavailable"
        self.app.call_from_thread(self.query_one("#detail-chart").update, f"[bold]Price Chart[/]\n{chart_str}")
        try: # fundamentals
            from stonks_cli.data.fundamentals import fetch_fundamentals_yahoo
            base = normalized.split(".")[0]
            fund = fetch_fundamentals_yahoo(base)
            if fund:
                lines = ["[bold]Fundamentals[/]\n"]
                for k, v in list(fund.items())[:10]:
                    lines.append(f"  {k}: {v}")
                fund_str = "\n".join(lines)
            else:
                fund_str = "[bold]Fundamentals[/]\n  N/A"
        except Exception:
            fund_str = "[bold]Fundamentals[/]\n  requires yfinance"
        self.app.call_from_thread(self.query_one("#detail-fundamentals").update, fund_str)
        try: # indicators
            from stonks_cli.analysis.indicators import bollinger_bands, rsi, sma
            close = df["close"].astype(float)
            rsi_val = rsi(close, 14).iloc[-1]
            sma_20 = sma(close, 20).iloc[-1]
            sma_50 = sma(close, 50).iloc[-1]
            lower, mid, upper = bollinger_bands(close)
            lines = ["[bold]Indicators[/]\n", f"  RSI(14): {rsi_val:.2f}", f"  SMA(20): {sma_20:.2f}", f"  SMA(50): {sma_50:.2f}", f"  BB upper: {float(upper.iloc[-1]):.2f}", f"  BB mid:   {float(mid.iloc[-1]):.2f}", f"  BB lower: {float(lower.iloc[-1]):.2f}"]
            self.app.call_from_thread(self.query_one("#detail-indicators").update, "\n".join(lines))
        except Exception as e:
            self.app.call_from_thread(self.query_one("#detail-indicators").update, f"[bold]Indicators[/]\n  error: {e}")
        try: # news
            from stonks_cli.data.news import fetch_news_rss
            base = normalized.split(".")[0]
            items = fetch_news_rss(base)
            lines = ["[bold]News[/]\n"]
            for item in items[:5]:
                title = item.get("title", "")[:60]
                lines.append(f"  {title}")
            self.app.call_from_thread(self.query_one("#detail-news").update, "\n".join(lines) if len(lines) > 1 else "[bold]News[/]\n  no news")
        except Exception:
            self.app.call_from_thread(self.query_one("#detail-news").update, "[bold]News[/]\n  unavailable")
        try: # backtest
            from stonks_cli.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
            bt = walk_forward_backtest(df, strategy_fn=strategy_fn, min_history_rows=cfg.risk.min_history_days)
            metrics = compute_backtest_metrics(bt.equity)
            lines = ["[bold]Backtest[/]\n"]
            if metrics:
                for k, v in [("cagr", metrics.cagr), ("sharpe", metrics.sharpe), ("max_dd", metrics.max_drawdown), ("win_rate", metrics.win_rate), ("trades", metrics.total_trades)]:
                    val = f"{v:.4f}" if isinstance(v, float) else str(v)
                    lines.append(f"  {k}: {val}")
            else:
                lines.append("  insufficient data")
            self.app.call_from_thread(self.query_one("#detail-backtest").update, "\n".join(lines))
        except Exception as e:
            self.app.call_from_thread(self.query_one("#detail-backtest").update, f"[bold]Backtest[/]\n  error: {e}")

    def refresh_data(self) -> None:
        if self._ticker:
            self._load_data(self._ticker)
