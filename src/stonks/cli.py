from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from apscheduler.triggers.cron import CronTrigger
from rich.console import Console

from stonks import __version__
from stonks.chat.repl import run_chat
from stonks.config import AppConfig, config_path, load_config, save_default_config
from stonks.pipeline import run_once
from stonks.scheduler.run import run_scheduler

app = typer.Typer(add_completion=True)
config_app = typer.Typer()
schedule_app = typer.Typer()

app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")


@app.command()
def version() -> None:
    """Print version."""
    Console().print(__version__)


@config_app.command("init")
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    p = Path(path).expanduser() if path else None
    out = save_default_config(p)
    Console().print(f"Created config: {out}")


@config_app.command("show")
def config_show() -> None:
    """Print effective config."""
    cfg = load_config()
    Console().print(cfg.model_dump_json(indent=2))


@config_app.command("where")
def config_where() -> None:
    """Print config path."""
    Console().print(str(config_path()))


@app.command()
def analyze(
    tickers: list[str] = typer.Argument(None),
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Analyze tickers and write a report."""
    cfg = load_config()
    if tickers:
        cfg = cfg.model_copy(update={"tickers": tickers})
    run_once(cfg, out_dir=Path(out_dir))


@schedule_app.command("run")
def schedule_run(out_dir: str = typer.Option("reports", "--out-dir")) -> None:
    """Run the cron-like scheduler in the foreground."""
    cfg = load_config()
    run_scheduler(cfg, out_dir=Path(out_dir))


@schedule_app.command("once")
def schedule_once(out_dir: str = typer.Option("reports", "--out-dir")) -> None:
    """Run one analysis+report (same as a single scheduled job)."""
    cfg = load_config()
    run_once(cfg, out_dir=Path(out_dir))


@schedule_app.command("status")
def schedule_status() -> None:
    """Show cron expression and next run time (best-effort)."""
    cfg: AppConfig = load_config()
    console = Console()
    console.print(f"cron: {cfg.schedule.cron}")
    try:
        trigger = CronTrigger.from_crontab(cfg.schedule.cron)
        next_dt = trigger.get_next_fire_time(None, datetime.now())
        console.print(f"next: {next_dt}")
    except Exception as e:
        console.print(f"next: [red]unavailable[/red] ({e})")


@app.command()
def chat() -> None:
    """Start an interactive chat UI using a local model backend."""
    cfg = load_config()
    run_chat(host=cfg.model.host, model=cfg.model.model)


def main() -> None:
    app()
