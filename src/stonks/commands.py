from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from apscheduler.triggers.cron import CronTrigger

from stonks import __version__
from stonks.config import AppConfig, config_path, load_config, save_default_config
from stonks.pipeline import run_once
from stonks.scheduler.run import SchedulerHandle, run_scheduler, start_scheduler_in_thread


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
