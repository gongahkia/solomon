from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from stonks.chat.repl import run_chat
from stonks.config import load_config
from stonks.commands import (
    do_analyze,
    do_analyze_artifacts,
    do_backtest,
    do_config_init,
    do_config_show,
    do_config_where,
    do_data_fetch,
    do_data_verify,
    do_history_list,
    do_history_show,
    do_doctor,
    do_ollama_check,
    do_report_open,
    do_schedule_once,
    do_schedule_run,
    do_schedule_status,
    do_version,
)

app = typer.Typer(add_completion=True)
config_app = typer.Typer()
schedule_app = typer.Typer()
data_app = typer.Typer()
report_app = typer.Typer()
history_app = typer.Typer()
llm_app = typer.Typer()

app.add_typer(config_app, name="config")
app.add_typer(schedule_app, name="schedule")
app.add_typer(data_app, name="data")
app.add_typer(report_app, name="report")
app.add_typer(history_app, name="history")
app.add_typer(llm_app, name="llm")


@app.command()
def version() -> None:
    """Print version."""
    Console().print(do_version())


@app.command()
def doctor() -> None:
    """Diagnose environment (config, data, LLM)."""
    results = do_doctor()
    for k, v in results.items():
        Console().print(f"{k}: {v}")


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
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
) -> None:
    """Analyze tickers and write a report."""
    if json_out:
        artifacts = do_analyze_artifacts(tickers if tickers else None, out_dir=Path(out_dir), json_out=True)
        Console().print(f"Wrote report: {artifacts.report_path}")
        if artifacts.json_path:
            Console().print(f"Wrote json: {artifacts.json_path}")
        return
    do_analyze(tickers if tickers else None, out_dir=Path(out_dir))


@app.command()
def backtest(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Run a simple walk-forward backtest and write a summary report."""
    path = do_backtest(
        tickers if tickers else None,
        start=start,
        end=end,
        out_dir=Path(out_dir),
    )
    Console().print(f"Wrote backtest: {path}")


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
    run_chat()


@llm_app.command("check")
def llm_check() -> None:
    """Check local LLM backend connectivity (Ollama)."""
    Console().print(do_ollama_check())


@data_app.command("fetch")
def data_fetch(tickers: list[str] = typer.Argument(None)) -> None:
    """Fetch price data for tickers (populates cache)."""
    fetched = do_data_fetch(tickers if tickers else None)
    Console().print(f"Fetched {len(fetched)} tickers")


@data_app.command("verify")
def data_verify(tickers: list[str] = typer.Argument(None)) -> None:
    """Verify data provider(s) for tickers."""
    results = do_data_verify(tickers if tickers else None)
    for t, status in results.items():
        Console().print(f"{t}: {status}")


@report_app.command("open")
def report_open() -> None:
    """Print latest report path (if any)."""
    try:
        p = do_report_open()
        Console().print(str(p))
    except FileNotFoundError as e:
        raise typer.Exit(code=2) from e


@history_app.command("list")
def history_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recent runs."""
    records = do_history_list(limit=limit)
    if not records:
        Console().print("No history")
        return
    for i, r in enumerate(records):
        Console().print(f"{i}: {r.started_at}  {','.join(r.tickers)}  {r.report_path}  {r.json_path}")


@history_app.command("show")
def history_show(index: int = typer.Argument(..., min=0), limit: int = typer.Option(2000, "--limit", min=1, max=2000)) -> None:
    """Show details for a prior run by index (within the last --limit entries)."""
    try:
        r = do_history_show(index, limit=limit)
    except IndexError as e:
        raise typer.Exit(code=2) from e
    Console().print(f"started_at: {r.started_at}")
    Console().print(f"tickers: {','.join(r.tickers)}")
    Console().print(f"report_path: {r.report_path}")
    Console().print(f"json_path: {r.json_path}")


def main() -> None:
    app()
