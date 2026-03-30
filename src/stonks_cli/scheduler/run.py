from __future__ import annotations

import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Lock, Thread
from time import perf_counter

from apscheduler.schedulers.blocking import BlockingScheduler
from rich.console import Console

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import log_suppressed_exception, track_event
from stonks_cli.pipeline import run_once
from stonks_cli.scheduler.pidfile import acquire_pid_file
from stonks_cli.scheduler.tz import cron_trigger_from_config, resolve_timezone
from stonks_cli.storage import default_state_dir, save_last_failure


@dataclass
class SchedulerHandle:
    scheduler: BlockingScheduler
    thread: Thread

    def stop(self) -> None:
        try:
            self.scheduler.shutdown(wait=False)
        except Exception as e:
            log_suppressed_exception(context="scheduler.handle.stop", error=e)


def build_scheduler(
    cfg: AppConfig,
    out_dir: Path,
    console: Console | None = None,
    *,
    report_name: str | None = None,
    csv_out: bool = False,
    sandbox: bool = False,
) -> BlockingScheduler:
    console = console or Console()
    run_lock = Lock()
    tz = resolve_timezone(cfg.schedule.timezone)

    def job() -> None:
        if not run_lock.acquire(blocking=False):
            console.print("[yellow]Scheduled run skipped[/yellow] previous run still active")
            return
        started = datetime.now()
        t0 = perf_counter()
        track_event("scheduler.job.started", started_at=started.isoformat())
        console.print(f"[cyan]Scheduled run started[/cyan] {started.isoformat()}")
        try:
            report_path = run_once(
                cfg,
                out_dir=out_dir,
                console=console,
                report_name=report_name,
                csv_out=csv_out,
                sandbox=sandbox,
            )
            ended = datetime.now()
            dt_s = perf_counter() - t0
            track_event(
                "scheduler.job.finished",
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                duration_seconds=round(dt_s, 4),
                report_path=report_path,
            )
            console.print(f"[cyan]Scheduled run finished[/cyan] {ended.isoformat()} ({dt_s:.2f}s) report={report_path}")

            # Check alerts after analysis
            try:
                from stonks_cli.commands import do_alert_check

                triggered = do_alert_check()
                if triggered:
                    console.print(f"[bold red]{len(triggered)} alert(s) triggered![/bold red]")
                    for a in triggered:
                        cond = a["condition_type"].replace("_", " ")
                        console.print(f"  • {a['ticker']} {cond} {a['threshold']}")
            except Exception as alert_err:
                log_suppressed_exception(context="scheduler.job.alert_check", error=alert_err)
                console.print(f"[yellow]Alert check failed:[/yellow] {alert_err}")

        except Exception as e:
            ended = datetime.now()
            dt_s = perf_counter() - t0
            track_event(
                "scheduler.job.failed",
                level=40,
                started_at=started.isoformat(),
                ended_at=ended.isoformat(),
                duration_seconds=round(dt_s, 4),
                error_type=type(e).__name__,
                error=str(e),
            )
            console.print(f"[red]Scheduled run failed[/red] {ended.isoformat()} ({dt_s:.2f}s) error={e}")
            try:
                save_last_failure(error=repr(e), where="scheduler")
            except Exception as save_err:
                log_suppressed_exception(context="scheduler.job.save_last_failure", error=save_err)
            return
        finally:
            try:
                run_lock.release()
            except Exception as e:
                log_suppressed_exception(context="scheduler.job.release_lock", error=e)

    trigger = cron_trigger_from_config(cfg.schedule.cron, cfg.schedule.timezone)
    scheduler = BlockingScheduler(timezone=tz)
    scheduler.add_job(job, trigger, max_instances=1)
    return scheduler


def run_scheduler(
    cfg: AppConfig,
    out_dir: Path,
    *,
    report_name: str | None = None,
    csv_out: bool = False,
    sandbox: bool = False,
) -> None:
    console = Console()
    pid = acquire_pid_file(default_state_dir() / "scheduler.pid")
    scheduler = build_scheduler(
        cfg,
        out_dir=out_dir,
        console=console,
        report_name=report_name,
        csv_out=csv_out,
        sandbox=sandbox,
    )
    console.print(f"[green]Scheduler running[/green] cron='{cfg.schedule.cron}'")

    def _shutdown(signum: int, _frame) -> None:
        try:
            name = signal.Signals(signum).name
        except Exception:
            name = str(signum)
        console.print(f"[yellow]Shutting down[/yellow] signal={name}")
        try:
            scheduler.shutdown(wait=False)
        except Exception as e:
            log_suppressed_exception(context="scheduler.run.shutdown_handler", error=e)

    old_int = signal.signal(signal.SIGINT, _shutdown)
    old_term = signal.signal(signal.SIGTERM, _shutdown)
    try:
        scheduler.start()
    finally:
        try:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
        except Exception as e:
            log_suppressed_exception(context="scheduler.run.restore_signals", error=e)
        pid.remove()


def start_scheduler_in_thread(
    cfg: AppConfig,
    out_dir: Path,
    *,
    report_name: str | None = None,
    csv_out: bool = False,
    sandbox: bool = False,
) -> SchedulerHandle:
    console = Console()
    scheduler = build_scheduler(
        cfg,
        out_dir=out_dir,
        console=console,
        report_name=report_name,
        csv_out=csv_out,
        sandbox=sandbox,
    )

    def runner() -> None:
        console.print(f"[green]Scheduler running (background)[/green] cron='{cfg.schedule.cron}'")
        scheduler.start()

    t = Thread(target=runner, daemon=True)
    t.start()
    return SchedulerHandle(scheduler=scheduler, thread=t)
