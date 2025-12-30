from __future__ import annotations

from pathlib import Path

from rich.console import Console

from stonks.analysis.indicators import atr, rolling_volatility
from stonks.analysis.risk import (
    scale_fractions_to_portfolio_cap,
    suggest_stop_loss_price_by_atr,
    suggest_position_fraction_by_volatility,
    suggest_take_profit_price_by_atr,
)
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
    per_ticker_fraction: dict[str, float] = {}
    for ticker in cfg.tickers:
        provider = provider_for(ticker)
        series = provider.fetch_daily(ticker)
        df = series.df
        last_close = None
        if "close" in df.columns and not df.empty:
            last_close = float(df["close"].iloc[-1])
        if len(df) < cfg.risk.min_history_days:
            rec = Recommendation(
                action="INSUFFICIENT_HISTORY",
                confidence=0.1,
                rationale=f"Need >={cfg.risk.min_history_days} rows",
            )
        else:
            rec = strategy_fn(df)
        if "volume" not in df.columns or df.empty:
            if rec.action in {"BUY_DCA", "HOLD_DCA"}:
                rec = Recommendation(
                    action="HOLD_WAIT",
                    confidence=min(0.4, rec.confidence),
                    rationale=f"{rec.rationale} | volume missing; avoid new buys",
                )
        else:
            try:
                v_last = float(df["volume"].iloc[-1])
            except Exception:
                v_last = 0.0
            if v_last <= 0 and rec.action in {"BUY_DCA", "HOLD_DCA"}:
                rec = Recommendation(
                    action="HOLD_WAIT",
                    confidence=min(0.4, rec.confidence),
                    rationale=f"{rec.rationale} | volume insufficient; avoid new buys",
                )
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
                per_ticker_fraction[series.ticker] = pos
                rec = Recommendation(
                    action=rec.action,
                    confidence=rec.confidence,
                    rationale=(
                        f"{rec.rationale} | sizing~{pos*100:.0f}% (ann vol {vol_f*100:.0f}%, cap {cfg.risk.max_position_fraction*100:.0f}%)"
                    ),
                )

        if {"high", "low", "close"}.issubset(set(df.columns)) and not df.empty:
            last = float(df["close"].iloc[-1])
            atr14 = atr(df["high"], df["low"], df["close"], window=14).iloc[-1]
            try:
                atr_f = float(atr14)
            except Exception:
                atr_f = float("nan")
            sl = suggest_stop_loss_price_by_atr(last, atr_f, multiple=2.0)
            tp = suggest_take_profit_price_by_atr(last, atr_f, multiple=3.0)
            if sl is not None and tp is not None:
                rec = Recommendation(
                    action=rec.action,
                    confidence=rec.confidence,
                    rationale=f"{rec.rationale} | stop~{sl:.2f} (2.0x ATR14 {atr_f:.2f}) | take~{tp:.2f} (3.0x ATR14)",
                )
            elif sl is not None:
                rec = Recommendation(
                    action=rec.action,
                    confidence=rec.confidence,
                    rationale=f"{rec.rationale} | stop~{sl:.2f} (2.0x ATR14 {atr_f:.2f})",
                )
            elif tp is not None:
                rec = Recommendation(
                    action=rec.action,
                    confidence=rec.confidence,
                    rationale=f"{rec.rationale} | take~{tp:.2f} (3.0x ATR14 {atr_f:.2f})",
                )
        results.append(TickerResult(ticker=series.ticker, last_close=last_close, recommendation=rec))

    scaled, factor = scale_fractions_to_portfolio_cap(
        per_ticker_fraction,
        max_portfolio_exposure_fraction=cfg.risk.max_portfolio_exposure_fraction,
    )
    if factor not in (0.0, 1.0):
        new_results: list[TickerResult] = []
        for r in results:
            frac = scaled.get(r.ticker)
            if frac is None:
                new_results.append(r)
                continue
            rec = Recommendation(
                action=r.recommendation.action,
                confidence=r.recommendation.confidence,
                rationale=(
                    f"{r.recommendation.rationale} | portfolio_cap {cfg.risk.max_portfolio_exposure_fraction*100:.0f}% (scaled x{factor:.2f}; now~{frac*100:.0f}%)"
                ),
            )
            new_results.append(TickerResult(ticker=r.ticker, last_close=r.last_close, recommendation=rec))
        results = new_results

    report_path = write_text_report(results, out_dir=out_dir)
    save_last_run(cfg.tickers, report_path)
    console.print(f"[green]Wrote report[/green] {report_path}")
    return report_path
