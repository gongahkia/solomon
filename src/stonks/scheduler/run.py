from __future__ import annotations

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Thread

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from stonks.config import AppConfig
from stonks.pipeline import run_once


@dataclass
class SchedulerHandle:
    scheduler: BlockingScheduler
    thread: Thread

    def stop(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass


def build_scheduler(cfg: AppConfig, out_dir: Path, console: Console | None = None) -> BlockingScheduler:
    console = console or Console()

    def job() -> None:
        started = datetime.now()
        console.print(f"[cyan]Scheduled run started[/cyan] {started.isoformat()}")
        run_once(cfg, out_dir=out_dir, console=console)

    trigger = CronTrigger.from_crontab(cfg.schedule.cron)
    scheduler = BlockingScheduler()
    scheduler.add_job(job, trigger)
    return scheduler


def run_scheduler(cfg: AppConfig, out_dir: Path) -> None:
    console = Console()
    scheduler = build_scheduler(cfg, out_dir=out_dir, console=console)
    console.print(f"[green]Scheduler running[/green] cron='{cfg.schedule.cron}'")
    scheduler.start()


def start_scheduler_in_thread(cfg: AppConfig, out_dir: Path) -> SchedulerHandle:
    console = Console()
    scheduler = build_scheduler(cfg, out_dir=out_dir, console=console)

    def runner() -> None:
        console.print(f"[green]Scheduler running (background)[/green] cron='{cfg.schedule.cron}'")
        scheduler.start()

    t = Thread(target=runner, daemon=True)
    t.start()
    return SchedulerHandle(scheduler=scheduler, thread=t)

