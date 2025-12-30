from __future__ import annotations

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from stonks.config import AppConfig
from stonks.pipeline import run_once


def run_scheduler(cfg: AppConfig, out_dir: Path) -> None:
    console = Console()

    def job() -> None:
        started = datetime.now()
        console.print(f"[cyan]Scheduled run started[/cyan] {started.isoformat()}")
        run_once(cfg, out_dir=out_dir, console=console)

    trigger = CronTrigger.from_crontab(cfg.schedule.cron)

    scheduler = BlockingScheduler()
    scheduler.add_job(job, trigger)
    console.print(f"[green]Scheduler running[/green] cron='{cfg.schedule.cron}'")
    scheduler.start()

