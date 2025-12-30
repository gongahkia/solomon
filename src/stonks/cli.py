from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from stonks.chat.repl import run_chat
from stonks.commands import (
    do_analyze,
    do_config_init,
    do_config_show,
    do_config_where,
    do_data_fetch,
    do_schedule_once,
    do_schedule_run,
    do_schedule_status,
    do_version,
)

app = typer.Typer(add_completion=True)
config_app = typer.Typer()
schedule_app = typer.Typer()
data_app = typer.Typer()

app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")
app.add_typer(data_app, name="data")


@app.command()
def version() -> None:
    """Print version."""
    Console().print(do_version())


@config_app.command("init")
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    p = Path(path).expanduser() if path else None
    out = do_config_init(p)
    Console().print(f"Created config: {out}")


@config_app.command("show")
def config_show() -> None:
    """Print effective config."""
    Console().print(do_config_show())


@config_app.command("where")
def config_where() -> None:
    """Print config path."""
    Console().print(str(do_config_where()))


@app.command()
def analyze(
    tickers: list[str] = typer.Argument(None),
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Analyze tickers and write a report."""
    do_analyze(tickers if tickers else None, out_dir=Path(out_dir))


@schedule_app.command("run")
def schedule_run(out_dir: str = typer.Option("reports", "--out-dir")) -> None:
    """Run the cron-like scheduler in the foreground."""
    do_schedule_run(out_dir=Path(out_dir))


@schedule_app.command("once")
def schedule_once(out_dir: str = typer.Option("reports", "--out-dir")) -> None:
    """Run one analysis+report (same as a single scheduled job)."""
    do_schedule_once(out_dir=Path(out_dir))


@schedule_app.command("status")
def schedule_status() -> None:
    """Show cron expression and next run time (best-effort)."""
    status = do_schedule_status()
    console = Console()
    console.print(f"cron: {status.cron}")
    if status.next_run:
        console.print(f"next: {status.next_run}")
    else:
        console.print(f"next: [red]unavailable[/red] ({status.error})")


@app.command()
def chat() -> None:
    """Start an interactive chat UI using a local model backend."""
    cfg = load_config()
    run_chat(host=cfg.model.host, model=cfg.model.model)


@data_app.command("fetch")
def data_fetch(tickers: list[str] = typer.Argument(None)) -> None:
    """Fetch price data for tickers (populates cache)."""
    fetched = do_data_fetch(tickers if tickers else None)
    Console().print(f"Fetched {len(fetched)} tickers")


def main() -> None:
    app()
