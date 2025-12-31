from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import signal
from time import perf_counter
from threading import Lock, Thread

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from stonks_cli.config import AppConfig
from stonks_cli.pipeline import run_once
from stonks_cli.scheduler.pidfile import acquire_pid_file
from stonks_cli.storage import default_state_dir


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
    run_lock = Lock()

    def job() -> None:
        if not run_lock.acquire(blocking=False):
            console.print("[yellow]Scheduled run skipped[/yellow] previous run still active")
            return
        started = datetime.now()
        t0 = perf_counter()
        console.print(f"[cyan]Scheduled run started[/cyan] {started.isoformat()}")
        try:
            report_path = run_once(cfg, out_dir=out_dir, console=console)
            ended = datetime.now()
            dt_s = perf_counter() - t0
            console.print(f"[cyan]Scheduled run finished[/cyan] {ended.isoformat()} ({dt_s:.2f}s) report={report_path}")
        except Exception as e:
            ended = datetime.now()
            dt_s = perf_counter() - t0
            console.print(f"[red]Scheduled run failed[/red] {ended.isoformat()} ({dt_s:.2f}s) error={e}")
            raise
        finally:
            try:
                run_lock.release()
            except Exception:
                pass

    trigger = CronTrigger.from_crontab(cfg.schedule.cron)
    scheduler = BlockingScheduler()
    scheduler.add_job(job, trigger, max_instances=1)
    return scheduler


def run_scheduler(cfg: AppConfig, out_dir: Path) -> None:
    console = Console()
    pid = acquire_pid_file(default_state_dir() / "scheduler.pid")
    scheduler = build_scheduler(cfg, out_dir=out_dir, console=console)
    console.print(f"[green]Scheduler running[/green] cron='{cfg.schedule.cron}'")

    def _shutdown(signum: int, _frame) -> None:
        try:
            name = signal.Signals(signum).name
        except Exception:
            name = str(signum)
        console.print(f"[yellow]Shutting down[/yellow] signal={name}")
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass

    old_int = signal.signal(signal.SIGINT, _shutdown)
    old_term = signal.signal(signal.SIGTERM, _shutdown)
    try:
        scheduler.start()
    finally:
        try:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
        except Exception:
            pass
        pid.remove()


def start_scheduler_in_thread(cfg: AppConfig, out_dir: Path) -> SchedulerHandle:
    console = Console()
    scheduler = build_scheduler(cfg, out_dir=out_dir, console=console)

    def runner() -> None:
        console.print(f"[green]Scheduler running (background)[/green] cron='{cfg.schedule.cron}'")
        scheduler.start()

    t = Thread(target=runner, daemon=True)
    t.start()
    return SchedulerHandle(scheduler=scheduler, thread=t)

