from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from stonks import __version__
from stonks.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
from stonks.config import AppConfig, config_path, load_config, save_default_config
from stonks.pipeline import STRATEGIES, provider_for_config, run_once
from stonks.scheduler.run import SchedulerHandle, run_scheduler, start_scheduler_in_thread
from stonks.data.providers import CsvProvider, StooqProvider
from stonks.reporting.backtest_report import BacktestRow, write_backtest_report


def do_version() -> str:
    return __version__


def do_config_where() -> Path:
    return config_path()


def do_config_init(path: Path | None) -> Path:
    return save_default_config(path)


def do_config_show() -> str:
    cfg = load_config()
    return cfg.model_dump_json(indent=2)


def do_analyze(tickers: list[str] | None, out_dir: Path) -> Path:
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})
    return run_once(cfg, out_dir=out_dir)


def do_backtest(
    tickers: list[str] | None,
    *,
    start: str | None,
    end: str | None,
    out_dir: Path,
) -> Path:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    strategy_fn = STRATEGIES.get(cfg.strategy, STRATEGIES["basic_trend_rsi"])

    rows: list[BacktestRow] = []
    for t in use:
        provider = provider_for_config(cfg, t)
        series = provider.fetch_daily(t)
        df = series.df
        if start:
            df = df.loc[start:]
        if end:
            df = df.loc[:end]
        bt = walk_forward_backtest(df, strategy_fn=strategy_fn, min_history_rows=cfg.risk.min_history_days)
        metrics = compute_backtest_metrics(bt.equity)
        rows.append(BacktestRow(ticker=series.ticker, metrics=metrics))

    return write_backtest_report(rows, out_dir)


def do_schedule_once(out_dir: Path) -> Path:
    cfg = load_config()
    return run_once(cfg, out_dir=out_dir)


def do_schedule_run(out_dir: Path) -> None:
    cfg = load_config()
    run_scheduler(cfg, out_dir=out_dir)


@dataclass(frozen=True)
class ScheduleStatus:
    cron: str
    next_run: str | None
    error: str | None


def do_schedule_status() -> ScheduleStatus:
    cfg: AppConfig = load_config()
    try:
        trigger = CronTrigger.from_crontab(cfg.schedule.cron)
        next_dt = trigger.get_next_fire_time(None, datetime.now())
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
        override = cfg.ticker_overrides.get(t)
        data_cfg = override.data if override else cfg.data
        if data_cfg.provider == "csv":
            if not data_cfg.csv_path:
                raise ValueError(f"csv provider requires csv_path for {t}")
            provider = CsvProvider(data_cfg.csv_path)
        else:
            provider = StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)
        provider.fetch_daily(t)
        fetched.append(t)
    return fetched


def do_data_verify(tickers: list[str] | None) -> dict[str, str]:
    cfg = load_config()
    use = tickers if tickers else cfg.tickers
    out: dict[str, str] = {}
    for t in use:
        try:
            override = cfg.ticker_overrides.get(t)
            data_cfg = override.data if override else cfg.data
            if data_cfg.provider == "csv":
                if not data_cfg.csv_path:
                    raise ValueError("csv_path missing")
                provider = CsvProvider(data_cfg.csv_path)
            else:
                provider = StooqProvider(cache_ttl_seconds=data_cfg.cache_ttl_seconds)
            series = provider.fetch_daily(t)
            out[t] = "ok" if not series.df.empty else "no_rows"
        except Exception as e:
            out[t] = f"error: {e}"
    return out
