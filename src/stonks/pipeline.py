from __future__ import annotations

from pathlib import Path

from rich.console import Console

from stonks.analysis.indicators import rolling_volatility
from stonks.analysis.risk import suggest_position_fraction_by_volatility
from stonks.analysis.strategy import (
    basic_trend_rsi_strategy,
    mean_reversion_bb_rsi_strategy,
    Recommendation,
    sma_cross_strategy,
)
from stonks.config import AppConfig
from stonks.data.providers import CsvProvider, PriceProvider, StooqProvider, normalize_ticker
from stonks.reporting.report import TickerResult, write_text_report
from stonks.storage import save_last_run


def run_once(cfg: AppConfig, out_dir: Path, console: Console | None = None) -> Path:
    console = console or Console()

    strategies = {
        "basic_trend_rsi": basic_trend_rsi_strategy,
        "sma_cross": sma_cross_strategy,
        "mean_reversion_bb_rsi": mean_reversion_bb_rsi_strategy,
    }
    strategy_fn = strategies.get(cfg.strategy, basic_trend_rsi_strategy)

    def provider_for(ticker: str) -> PriceProvider:
        t = normalize_ticker(ticker)
        override = cfg.ticker_overrides.get(t)
        data_cfg = override.data if override else cfg.data
        if data_cfg.provider == "csv":
            if not data_cfg.csv_path:
                raise ValueError(f"csv provider requires csv_path for {t}")
            return CsvProvider(data_cfg.csv_path)
        return StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)

    results: list[TickerResult] = []
    for ticker in cfg.tickers:
        provider = provider_for(ticker)
        series = provider.fetch_daily(ticker)
        df = series.df
        last_close = None
        if "close" in df.columns and not df.empty:
            last_close = float(df["close"].iloc[-1])
        rec = strategy_fn(df)
        if "close" in df.columns and not df.empty:
            vol = rolling_volatility(df["close"], window=20).iloc[-1]
            try:
                vol_f = float(vol)
            except Exception:
                vol_f = float("nan")
            pos = suggest_position_fraction_by_volatility(
                vol_f,
                max_fraction=cfg.risk.max_position_fraction,
            )
            if pos is not None:
                rec = Recommendation(
                    action=rec.action,
                    confidence=rec.confidence,
                    rationale=(
                        f"{rec.rationale} | sizing~{pos*100:.0f}% (ann vol {vol_f*100:.0f}%, cap {cfg.risk.max_position_fraction*100:.0f}%)"
                    ),
                )
        results.append(TickerResult(ticker=series.ticker, last_close=last_close, recommendation=rec))

    report_path = write_text_report(results, out_dir=out_dir)
    save_last_run(cfg.tickers, report_path)
    console.print(f"[green]Wrote report[/green] {report_path}")
    return report_path
