from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from stonks_cli import __version__
from stonks_cli.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
from rich.console import Console

from stonks_cli.analysis.output import AnalysisArtifacts
from stonks_cli.config import AppConfig, config_path, load_config, save_config, save_default_config, update_config_field
from stonks_cli.pipeline import compute_results, provider_for_config, run_once, select_strategy
from stonks_cli.scheduler.run import SchedulerHandle, run_scheduler, start_scheduler_in_thread
from stonks_cli.scheduler.tz import cron_trigger_from_config, resolve_timezone
from stonks_cli.data.providers import CsvProvider, StooqProvider
from stonks_cli.reporting.backtest_report import BacktestRow, write_backtest_report
from stonks_cli.reporting.csv_report import write_csv_summary
from stonks_cli.reporting.json_report import write_json_report
from stonks_cli.reporting.report import write_text_report
from stonks_cli.storage import get_history_record, get_last_report_path, get_last_run, list_history, save_last_run
from stonks_cli.data.providers import normalize_ticker


@dataclass(frozen=True)
class QuickResult:
    ticker: str
    price: float | None
    change_pct: float | None
    action: str
    confidence: float
    prices: list[float] | None = None  # Last N closing prices for sparkline


def _fetch_quick_single(ticker: str, cfg: AppConfig, strategy_fn) -> QuickResult:
    """Internal helper to fetch and analyze a single ticker."""
    normalized = normalize_ticker(ticker)
    provider = provider_for_config(cfg, normalized)
    series = provider.fetch_daily(normalized)
    df = series.df

    if df.empty or "close" not in df.columns:
        return QuickResult(
            ticker=normalized,
            price=None,
            change_pct=None,
            action="NO_DATA",
            confidence=0.0,
            prices=None,
        )

    last_close = float(df["close"].iloc[-1])
    change_pct = None
    if len(df) >= 2:
        prev_close = float(df["close"].iloc[-2])
        if prev_close != 0:
            change_pct = ((last_close - prev_close) / prev_close) * 100

    # Extract last 20 prices for sparkline
    prices = df["close"].tail(20).tolist()

    if len(df) < cfg.risk.min_history_days:
        return QuickResult(
            ticker=normalized,
            price=last_close,
            change_pct=change_pct,
            action="INSUFFICIENT_HISTORY",
            confidence=0.1,
            prices=prices,
        )

    rec = strategy_fn(df)
    return QuickResult(
        ticker=normalized,
        price=last_close,
        change_pct=change_pct,
        action=rec.action,
        confidence=rec.confidence,
        prices=prices,
    )


def do_quick(tickers: list[str]) -> list[QuickResult]:
    """Fetch latest price and run strategy for one or more tickers concurrently."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cfg = load_config()
    strategy_fn = select_strategy(cfg)

    if len(tickers) == 1:
        return [_fetch_quick_single(tickers[0], cfg, strategy_fn)]

    results: list[QuickResult] = []
    max_workers = min(cfg.data.concurrency_limit, max(1, len(tickers)))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_quick_single, t, cfg, strategy_fn): t for t in tickers}
        for fut in as_completed(futures):
            results.append(fut.result())

    # Sort results to match input order
    ticker_order = {normalize_ticker(t): i for i, t in enumerate(tickers)}
    results.sort(key=lambda r: ticker_order.get(r.ticker, 999))
    return results


def do_fundamentals(ticker: str, as_json: bool = False) -> dict | None:
    """Fetch and return fundamental data for a ticker."""
    from stonks_cli.data.fundamentals import fetch_fundamentals_yahoo

    normalized = normalize_ticker(ticker)
    base_ticker = normalized.split(".")[0]
    fundamentals = fetch_fundamentals_yahoo(base_ticker)

    if fundamentals is None:
        return None

    if as_json:
        return fundamentals.to_dict()
    return fundamentals.to_dict()


def do_watch(watchlist_name: str | None = None, refresh_interval: int = 60) -> None:
    """Launch the watchlist TUI."""
    from stonks_cli.tui.watchlist_view import WatchlistTUI

    tui = WatchlistTUI(watchlist_name=watchlist_name, refresh_interval=refresh_interval)
    tui.run()


def do_chart_rsi(ticker: str, period: int = 14, days: int = 90) -> None:
    """Fetch data and display an RSI chart for a ticker."""
    from stonks_cli.charts.indicators import plot_rsi

    cfg = load_config()
    normalized = normalize_ticker(ticker)
    provider = provider_for_config(cfg, normalized)
    series = provider.fetch_daily(normalized)
    plot_rsi(series.df, normalized, period=period, days=days)


def do_chart_compare(tickers: list[str], days: int = 90) -> None:
    """Fetch data and display a comparison chart for multiple tickers."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from stonks_cli.charts.comparison import plot_comparison

    cfg = load_config()
    dfs: dict[str, object] = {}
    normalized_tickers = [normalize_ticker(t) for t in tickers]

    def _fetch(t: str):
        provider = provider_for_config(cfg, t)
        return t, provider.fetch_daily(t).df

    max_workers = min(cfg.data.concurrency_limit, max(1, len(normalized_tickers)))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(_fetch, t) for t in normalized_tickers]
        for fut in as_completed(futures):
            ticker, df = fut.result()
            dfs[ticker] = df

    plot_comparison(normalized_tickers, dfs, days=days)


def do_chart(
    ticker: str,
    days: int = 90,
    candle: bool = False,
    volume: bool = False,
    sma_periods: list[int] | None = None,
    show_bb: bool = False,
) -> None:
    """Fetch data and display a price chart for a ticker."""
    cfg = load_config()
    normalized = normalize_ticker(ticker)
    provider = provider_for_config(cfg, normalized)
    series = provider.fetch_daily(normalized)

    if candle:
        from stonks_cli.charts.candlestick import plot_candlestick

        plot_candlestick(series.df, normalized, days=days)
    elif volume:
        from stonks_cli.charts.price_chart import plot_with_volume

        plot_with_volume(series.df, normalized, days=days)
    else:
        from stonks_cli.charts.price_chart import plot_price_history

        plot_price_history(series.df, normalized, days=days, sma_periods=sma_periods, show_bb=show_bb)


def do_watchlist_list() -> dict[str, list[str]]:
    cfg = load_config()
    return {k: list(v or []) for k, v in (cfg.watchlists or {}).items()}


def do_watchlist_set(name: str, tickers: list[str]) -> dict[str, list[str]]:
    from stonks_cli.data.providers import normalize_ticker

    n = (name or "").strip()
    if not n:
        raise ValueError("watchlist name must be non-empty")
    cfg = load_config()
    watchlists = dict(cfg.watchlists or {})
    watchlists[n] = [normalize_ticker(t) for t in (tickers or [])]
    cfg = cfg.model_copy(update={"watchlists": watchlists})
    save_config(cfg)
    return {k: list(v or []) for k, v in (cfg.watchlists or {}).items()}


def do_watchlist_remove(name: str) -> dict[str, list[str]]:
    n = (name or "").strip()
    if not n:
        raise ValueError("watchlist name must be non-empty")
    cfg = load_config()
    watchlists = dict(cfg.watchlists or {})
    if n not in watchlists:
        raise KeyError(f"watchlist not found: {n}")
    watchlists.pop(n, None)
    cfg = cfg.model_copy(update={"watchlists": watchlists})
    save_config(cfg)
    return {k: list(v or []) for k, v in (cfg.watchlists or {}).items()}


def do_watchlist_analyze(
    name: str,
    *,
    out_dir: Path,
    start: str | None = None,
    end: str | None = None,
    report_name: str | None = None,
    json_out: bool = False,
    csv_out: bool = False,
    sandbox: bool = False,
) -> AnalysisArtifacts:
    cfg = load_config()
    n = (name or "").strip()
    if not n:
        raise ValueError("watchlist name must be non-empty")
    tickers = list((cfg.watchlists or {}).get(n) or [])
    if not tickers:
        raise KeyError(f"watchlist not found or empty: {n}")
    return do_analyze_artifacts(
        tickers,
        out_dir=out_dir,
        json_out=json_out,
        csv_out=csv_out,
        start=start,
        end=end,
        report_name=report_name,
        sandbox=sandbox,
    )


def do_signals_diff() -> dict[str, object]:
    """Compare latest vs previous run using JSON reports.

    Returns a small structured payload suitable for CLI rendering.
    """

    records = list_history(limit=2)
    if len(records) < 2:
        raise FileNotFoundError("Need at least two runs in history")

    latest, prev = records[0], records[1]
    if not latest.json_path or not prev.json_path:
        raise FileNotFoundError("Both latest and previous runs must have json_path recorded")

    latest_payload = json.loads(Path(latest.json_path).read_text(encoding="utf-8"))
    prev_payload = json.loads(Path(prev.json_path).read_text(encoding="utf-8"))

    def _map(payload: dict) -> dict[str, dict[str, object]]:
        out: dict[str, dict[str, object]] = {}
        for r in payload.get("results") or []:
            try:
                t = str(r.get("ticker"))
            except Exception:
                continue
            out[t] = {
                "action": r.get("action"),
                "confidence": r.get("confidence"),
            }
        return out

    latest_map = _map(latest_payload)
    prev_map = _map(prev_payload)

    tickers = sorted(set(latest_map.keys()) | set(prev_map.keys()))
    changes: list[dict[str, object]] = []
    for t in tickers:
        a_new = latest_map.get(t, {}).get("action")
        a_old = prev_map.get(t, {}).get("action")
        c_new = latest_map.get(t, {}).get("confidence")
        c_old = prev_map.get(t, {}).get("confidence")

        if t not in prev_map:
            changes.append({"ticker": t, "kind": "ADDED", "old": None, "new": a_new, "delta": None})
            continue
        if t not in latest_map:
            changes.append({"ticker": t, "kind": "REMOVED", "old": a_old, "new": None, "delta": None})
            continue

        try:
            delta = float(c_new) - float(c_old)
        except Exception:
            delta = None

        if a_new != a_old or (delta is not None and abs(delta) >= 1e-9):
            changes.append(
                {
                    "ticker": t,
                    "kind": "CHANGED" if a_new != a_old else "CONFIDENCE_ONLY",
                    "old": {"action": a_old, "confidence": c_old},
                    "new": {"action": a_new, "confidence": c_new},
                    "delta": delta,
                }
            )

    return {
        "latest": latest.started_at,
        "previous": prev.started_at,
        "count": len(changes),
        "changes": changes,
    }


def do_plugins_list() -> dict[str, object]:
    cfg = load_config()
    from stonks_cli.plugins import load_plugins_best_effort

    specs = tuple(cfg.plugins or [])
    summary = load_plugins_best_effort(specs)
    return {
        "configured": list(specs),
        "ok": list(summary.ok),
        "errors": dict(summary.errors),
        "strategies": sorted((summary.registry.strategies or {}).keys()),
        "provider_factories": sorted((summary.registry.provider_factories or {}).keys()),
    }


def do_version() -> str:
    return __version__


def do_doctor() -> dict[str, str]:
    cfg = load_config()
    out: dict[str, str] = {}
    try:
        out["config_path"] = str(config_path())
        out["config_loaded"] = "ok"
    except Exception as e:
        out["config_loaded"] = f"error: {e}"

    try:
        from stonks_cli.paths import default_cache_dir, default_state_dir

        out["cache_dir"] = str(default_cache_dir())
        out["state_dir"] = str(default_state_dir())
    except Exception as e:
        out["paths"] = f"error: {e}"

    # Data provider check (best-effort): uses configured provider for first ticker.
    try:
        tickers = cfg.tickers or []
        if not tickers:
            out["data_provider"] = "skipped (no tickers)"
        else:
            provider = provider_for_config(cfg, tickers[0])
            series = provider.fetch_daily(tickers[0])
            out["data_provider"] = "ok" if not series.df.empty else "no_rows"
            out["data_provider_type"] = type(provider).__name__
    except Exception as e:
        out["data_provider"] = f"error: {e}"

    # Plugin load status (best-effort): report per-plugin success/errors.
    try:
        from stonks_cli.plugins import load_plugins_best_effort

        specs = tuple(cfg.plugins or [])
        if not specs:
            out["plugins"] = "skipped (none configured)"
        else:
            summary = load_plugins_best_effort(specs)
            out["plugins_ok"] = str(len(summary.ok))
            out["plugins_errors"] = str(len(summary.errors))
            out["plugins_strategies"] = str(len(summary.registry.strategies or {}))
            out["plugins_provider_factories"] = str(len(summary.registry.provider_factories or {}))
            if summary.errors:
                # Keep output compact; CLI prints key/value lines.
                out["plugins_error_detail"] = "; ".join(f"{k}: {v}" for k, v in summary.errors.items())
    except Exception as e:
        out["plugins"] = f"error: {e}"
    return out


def do_config_where() -> Path:
    return config_path()


def do_config_init(path: Path | None) -> Path:
    return save_default_config(path)


def do_config_show() -> str:
    cfg = load_config()
    return cfg.model_dump_json(indent=2)


def do_config_set(field_path: str, value) -> str:
    cfg = load_config()
    updated = update_config_field(cfg, field_path, value)
    save_config(updated)
    return updated.model_dump_json(indent=2)


def do_config_validate() -> dict[str, object]:
    cfg = load_config()

    tickers = list(cfg.tickers or [])
    providers: dict[str, str] = {}
    for t in tickers:
        p = provider_for_config(cfg, t)
        providers[t] = type(p).__name__

    return {
        "tickers": tickers,
        "providers": providers,
        "strategy": cfg.strategy,
    }


def do_analyze(
    tickers: list[str] | None,
    out_dir: Path,
    *,
    start: str | None = None,
    end: str | None = None,
    report_name: str | None = None,
    csv_out: bool = False,
    sandbox: bool = False,
) -> Path:
    artifacts = do_analyze_artifacts(
        tickers,
        out_dir=out_dir,
        json_out=False,
        csv_out=csv_out,
        start=start,
        end=end,
        report_name=report_name,
        sandbox=sandbox,
    )
    return artifacts.report_path


def do_analyze_artifacts(
    tickers: list[str] | None,
    *,
    out_dir: Path,
    json_out: bool,
    csv_out: bool = False,
    start: str | None = None,
    end: str | None = None,
    report_name: str | None = None,
    sandbox: bool = False,
) -> AnalysisArtifacts:
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})

    console = Console()
    results, portfolio = compute_results(cfg, console, start=start, end=end)
    report_path = write_text_report(results, out_dir=out_dir, portfolio=portfolio, name=report_name)

    if csv_out:
        csv_path = out_dir / f"{report_path.stem}.csv"
        write_csv_summary(results, out_path=csv_path)

    json_path = None
    if json_out:
        json_path = out_dir / f"{report_path.stem}.json"
        write_json_report(results, out_path=json_path, portfolio=portfolio)

    if not sandbox:
        save_last_run(cfg.tickers, report_path, json_path=json_path)

    return AnalysisArtifacts(report_path=report_path, json_path=json_path, portfolio=portfolio, results=results)


def do_bench(tickers: list[str] | None, *, iterations: int = 5, warmup: int = 1) -> str:
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})

    # Avoid mixing benchmark timing with I/O-heavy report generation.
    console = Console()

    for _ in range(max(0, warmup)):
        compute_results(cfg, console)

    timings: list[float] = []
    for _ in range(iterations):
        start = perf_counter()
        compute_results(cfg, console)
        timings.append(perf_counter() - start)

    timings_sorted = sorted(timings)
    avg = sum(timings) / len(timings)
    p50 = timings_sorted[len(timings_sorted) // 2]
    p95 = timings_sorted[max(0, int(len(timings_sorted) * 0.95) - 1)]
    return (
        f"benchmark tickers={len(cfg.tickers)} iterations={iterations} "
        f"avg={avg:.4f}s p50={p50:.4f}s p95={p95:.4f}s"
    )


def do_backtest(
    tickers: list[str] | None,
    *,
    start: str | None,
    end: str | None,
    out_dir: Path,
) -> Path:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    strategy_fn = select_strategy(cfg)

    rows: list[BacktestRow] = []
    for t in use:
        provider = provider_for_config(cfg, t)
        series = provider.fetch_daily(t)
        df = series.df
        if start:
            df = df.loc[start:]
        if end:
            df = df.loc[:end]
        bt = walk_forward_backtest(
            df,
            strategy_fn=strategy_fn,
            min_history_rows=cfg.risk.min_history_days,
            fee_bps=cfg.backtest.fee_bps,
            slippage_bps=cfg.backtest.slippage_bps,
        )
        metrics = compute_backtest_metrics(bt.equity)
        rows.append(BacktestRow(ticker=series.ticker, metrics=metrics))

    return write_backtest_report(rows, out_dir)


def do_report_open() -> Path:
    p = get_last_report_path()
    if p is None:
        raise FileNotFoundError("No last report recorded")
    return p


def do_report_view(path: Path | None = None) -> dict[str, str]:
    """Return the report path + text for viewing.

    If `path` is None, uses the last recorded report.
    """

    p = path if path is not None else do_report_open()
    return {
        "path": str(p),
        "text": p.read_text(encoding="utf-8"),
    }


def do_report_latest(*, include_json: bool = False) -> dict[str, str | None]:
    last = get_last_run()
    if last is None:
        raise FileNotFoundError("No last report recorded")
    return {
        "report_path": last.report_path,
        "json_path": last.json_path if include_json else None,
    }


def do_history_list(limit: int = 20):
    return list_history(limit=limit)


def do_history_show(index: int, *, limit: int = 2000):
    return get_history_record(index, limit=limit)


def do_schedule_once(
    out_dir: Path,
    *,
    sandbox: bool = False,
    report_name: str | None = None,
    csv_out: bool = False,
) -> Path:
    cfg = load_config()
    return run_once(cfg, out_dir=out_dir, sandbox=sandbox, report_name=report_name, csv_out=csv_out)


def do_schedule_run(
    out_dir: Path,
    *,
    report_name: str | None = None,
    csv_out: bool = False,
    sandbox: bool = False,
) -> None:
    cfg = load_config()
    run_scheduler(cfg, out_dir=out_dir, report_name=report_name, csv_out=csv_out, sandbox=sandbox)


@dataclass(frozen=True)
class ScheduleStatus:
    cron: str
    next_run: str | None
    error: str | None


def do_schedule_status() -> ScheduleStatus:
    cfg: AppConfig = load_config()
    try:
        tz = resolve_timezone(cfg.schedule.timezone)
        trigger = cron_trigger_from_config(cfg.schedule.cron, cfg.schedule.timezone)
        next_dt = trigger.get_next_fire_time(None, datetime.now(tz=tz))
        return ScheduleStatus(cron=cfg.schedule.cron, next_run=str(next_dt), error=None)
    except Exception as e:
        return ScheduleStatus(cron=cfg.schedule.cron, next_run=None, error=str(e))


def do_schedule_start_background(out_dir: Path) -> SchedulerHandle:
    cfg = load_config()
    return start_scheduler_in_thread(cfg, out_dir=out_dir)


def do_data_fetch(tickers: list[str] | None) -> list[str]:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    fetched: list[str] = []
    for t in use:
        provider = provider_for_config(cfg, t)
        provider.fetch_daily(t)
        fetched.append(t)
    return fetched


def do_data_verify(tickers: list[str] | None) -> dict[str, str]:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    def _health_check(series) -> str:
        df = series.df
        if df is None or getattr(df, "empty", True):
            return "no_rows"
        missing = [c for c in ["close"] if c not in df.columns]
        if missing:
            return f"missing_columns: {','.join(missing)}"
        if "close" in df.columns and df["close"].isna().any():
            return "bad_data: close_has_nans"
        try:
            if getattr(df.index, "is_monotonic_increasing", True) is False:
                return "bad_data: index_not_monotonic"
        except Exception:
            pass
        return "ok"

    out: dict[str, str] = {}
    for t in use:
        try:
            override = cfg.ticker_overrides.get(t)
            data_cfg = override.data if override else cfg.data
            if data_cfg.provider == "csv":
                if not data_cfg.csv_path:
                    raise ValueError("csv_path missing")
                provider = CsvProvider(data_cfg.csv_path)
            elif data_cfg.provider == "plugin":
                provider = provider_for_config(cfg, t)
            else:
                provider = StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)
            series = provider.fetch_daily(t)
            out[t] = _health_check(series)
        except Exception as e:
            out[t] = f"error: {e}"
    return out


def do_data_cache_info() -> dict[str, object]:
    from stonks_cli.paths import default_cache_dir

    cache_dir = default_cache_dir()
    if not cache_dir.exists():
        return {"cache_dir": str(cache_dir), "entries": 0, "size_bytes": 0, "examples": []}

    files = [p for p in cache_dir.glob("*.json") if p.is_file()]
    size_bytes = 0
    for p in files:
        try:
            size_bytes += p.stat().st_size
        except Exception:
            continue
    examples = [p.name for p in sorted(files)[:3]]
    return {
        "cache_dir": str(cache_dir),
        "entries": len(files),
        "size_bytes": size_bytes,
        "examples": examples,
    }


def do_data_purge(*, older_than_days: int | None = None) -> dict[str, object]:
    import json
    import time

    from stonks_cli.paths import default_cache_dir

    cache_dir = default_cache_dir()
    if not cache_dir.exists():
        return {"cache_dir": str(cache_dir), "deleted": 0}

    cutoff = None
    if older_than_days is not None:
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")
        cutoff = time.time() - (older_than_days * 86400)

    deleted = 0
    for p in cache_dir.glob("*.json"):
        if not p.is_file():
            continue
        should_delete = cutoff is None
        if cutoff is not None:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                created_at = float(data.get("created_at", 0))
            except Exception:
                try:
                    created_at = float(p.stat().st_mtime)
                except Exception:
                    created_at = 0.0
            should_delete = created_at <= cutoff

        if should_delete:
            try:
                p.unlink(missing_ok=True)
                deleted += 1
            except Exception:
                continue

    return {"cache_dir": str(cache_dir), "deleted": deleted}
