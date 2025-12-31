from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from rich.console import Console
from rich.progress import Progress

from stonks.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
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
from stonks.plugins import registry_for_config
from stonks.reporting.report import TickerResult, write_text_report
from stonks.storage import save_last_run


STRATEGIES = {
    "basic_trend_rsi": basic_trend_rsi_strategy,
    "sma_cross": sma_cross_strategy,
    "mean_reversion_bb_rsi": mean_reversion_bb_rsi_strategy,
}


def select_strategy(cfg: AppConfig):
    plugins = registry_for_config(cfg)
    combined = {**STRATEGIES, **(plugins.strategies or {})}
    return combined.get(cfg.strategy, combined["basic_trend_rsi"])


def provider_for_config(cfg: AppConfig, ticker: str) -> PriceProvider:
    t = normalize_ticker(ticker)
    override = cfg.ticker_overrides.get(t)
    data_cfg = override.data if override else cfg.data
    if data_cfg.provider == "csv":
        if not data_cfg.csv_path:
            raise ValueError(f"csv provider requires csv_path for {t}")
        return CsvProvider(data_cfg.csv_path)
    if data_cfg.provider == "plugin":
        if not data_cfg.plugin_name:
            raise ValueError(f"plugin provider requires plugin_name for {t}")
        plugins = registry_for_config(cfg)
        factory = (plugins.provider_factories or {}).get(data_cfg.plugin_name)
        if factory is None:
            raise ValueError(f"unknown plugin provider: {data_cfg.plugin_name}")
        provider = factory(cfg, t)
        if not hasattr(provider, "fetch_daily"):
            raise TypeError(f"plugin provider '{data_cfg.plugin_name}' must implement fetch_daily")
        return provider  # type: ignore[return-value]
    return StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)


def compute_results(cfg: AppConfig, console: Console) -> tuple[list[TickerResult], object | None]:
    strategy_fn = select_strategy(cfg)

    tickers = [normalize_ticker(t) for t in (cfg.tickers or [])]
    if cfg.deterministic:
        tickers = sorted(tickers)
    # Fetch in parallel to reduce wall-clock time for multiple tickers.
    series_by_ticker: dict[str, object] = {}

    def _fetch(t: str):
        provider = provider_for_config(cfg, t)
        return t, provider.fetch_daily(t)

    with Progress(transient=True, console=console) as progress:
        task = progress.add_task("Fetching prices", total=len(tickers))
        max_workers = 1 if cfg.deterministic else min(cfg.data.concurrency_limit, max(1, len(tickers)))
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = [ex.submit(_fetch, t) for t in tickers]
            for fut in as_completed(futs):
                t, series = fut.result()
                series_by_ticker[t] = series
                progress.advance(task)

    results: list[TickerResult] = []
    per_ticker_fraction: dict[str, float] = {}
    per_ticker_equity: dict[str, object] = {}
    for ticker in tickers:
        series = series_by_ticker[ticker]
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

        bt = walk_forward_backtest(df, strategy_fn=strategy_fn, min_history_rows=cfg.risk.min_history_days)
        metrics = compute_backtest_metrics(bt.equity)
        if bt.equity is not None and not bt.equity.empty:
            per_ticker_equity[series.ticker] = bt.equity

        results.append(
            TickerResult(
                ticker=series.ticker,
                last_close=last_close,
                recommendation=rec,
                backtest=metrics,
            )
        )

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

    portfolio_metrics = None
    if per_ticker_equity:
        import pandas as pd

        rets = []
        for eq in per_ticker_equity.values():
            s = eq.pct_change().fillna(0.0)
            rets.append(s)
        if rets:
            rets_df = pd.concat(rets, axis=1).fillna(0.0)
            port_ret = rets_df.mean(axis=1)
            port_equity = (1.0 + port_ret).cumprod()
            portfolio_metrics = compute_backtest_metrics(port_equity)

    return results, portfolio_metrics


def run_once(cfg: AppConfig, out_dir: Path, console: Console | None = None, *, sandbox: bool = False) -> Path:
    console = console or Console()
    results, portfolio_metrics = compute_results(cfg, console)
    report_path = write_text_report(results, out_dir=out_dir, portfolio=portfolio_metrics)
    if not sandbox:
        save_last_run(cfg.tickers, report_path)
    console.print(f"[green]Wrote report[/green] {report_path}")
    return report_path
