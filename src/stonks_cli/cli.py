from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pydantic import ValidationError

from stonks_cli.chat.repl import run_chat
from stonks_cli.config import load_config
from stonks_cli.commands import (
    do_analyze,
    do_analyze_artifacts,
    do_backtest,
    do_bench,
    do_config_init,
    do_config_show,
    do_config_where,
    do_data_fetch,
    do_data_verify,
    do_history_list,
    do_history_show,
    do_doctor,
    do_llm_check,
    do_report_open,
    do_schedule_once,
    do_schedule_run,
    do_schedule_status,
    do_version,
)
from stonks_cli.errors import ExitCodes, StonksError
from stonks_cli.logging_utils import LoggingConfig, configure_logging

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


@app.callback()
def _global_options(
    verbose: int = typer.Option(0, "--verbose", "-v", count=True, help="Increase logging verbosity"),
    quiet: bool = typer.Option(False, "--quiet", help="Only show errors"),
    structured_logs: bool = typer.Option(False, "--structured-logs", help="Emit JSON lines logs to stderr"),
) -> None:
    configure_logging(LoggingConfig(verbose=verbose, quiet=quiet, structured=structured_logs))


def _exit_for_error(e: Exception) -> typer.Exit:
    if isinstance(e, StonksError):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=e.code)
    if isinstance(e, ValidationError):
        Console().print(f"[red]Bad config:[/red] {e}")
        return typer.Exit(code=ExitCodes.BAD_CONFIG)
    if isinstance(e, (FileNotFoundError, IndexError, ValueError)):
        Console().print(f"[red]Error:[/red] {e}")
        return typer.Exit(code=ExitCodes.USAGE_ERROR)
    Console().print(f"[red]Error:[/red] {e}")
    return typer.Exit(code=ExitCodes.UNKNOWN_ERROR)


@app.command()
def version() -> None:
    """Print version."""
    try:
        Console().print(do_version())
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def doctor() -> None:
    """Diagnose environment (config, data, LLM)."""
    try:
        results = do_doctor()
        for k, v in results.items():
            Console().print(f"{k}: {v}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("init")
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    try:
        p = Path(path).expanduser() if path else None
        out = do_config_init(p)
        Console().print(f"Created config: {out}")
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("show")
def config_show() -> None:
    """Print effective config."""
    try:
        Console().print(do_config_show())
    except Exception as e:
        raise _exit_for_error(e)


@config_app.command("where")
def config_where() -> None:
    """Print config path."""
    try:
        Console().print(str(do_config_where()))
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def analyze(
    tickers: list[str] = typer.Argument(None),
    out_dir: str = typer.Option("reports", "--out-dir"),
    json_out: bool = typer.Option(False, "--json", "--no-json", help="Write JSON output alongside the report"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Analyze tickers and write a report."""
    try:
        if json_out:
            artifacts = do_analyze_artifacts(
                tickers if tickers else None,
                out_dir=Path(out_dir),
                json_out=True,
                sandbox=sandbox,
            )
            Console().print(f"Wrote report: {artifacts.report_path}")
            if artifacts.json_path:
                Console().print(f"Wrote json: {artifacts.json_path}")
            return
        do_analyze(tickers if tickers else None, out_dir=Path(out_dir), sandbox=sandbox)
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def backtest(
    tickers: list[str] = typer.Argument(None),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM-DD"),
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Run a simple walk-forward backtest and write a summary report."""
    try:
        path = do_backtest(
            tickers if tickers else None,
            start=start,
            end=end,
            out_dir=Path(out_dir),
        )
        Console().print(f"Wrote backtest: {path}")
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def bench(
    tickers: list[str] = typer.Argument(None),
    iterations: int = typer.Option(5, "--iterations", min=1, max=50),
    warmup: int = typer.Option(1, "--warmup", min=0, max=10),
) -> None:
    """Run a simple multi-ticker analysis benchmark."""
    try:
        summary = do_bench(tickers if tickers else None, iterations=iterations, warmup=warmup)
        Console().print(summary)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("run")
def schedule_run(out_dir: str = typer.Option("reports", "--out-dir")) -> None:
    """Run the cron-like scheduler in the foreground."""
    try:
        do_schedule_run(out_dir=Path(out_dir))
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("once")
def schedule_once(
    out_dir: str = typer.Option("reports", "--out-dir"),
    sandbox: bool = typer.Option(False, "--sandbox", help="Run without persisting last-run history"),
) -> None:
    """Run one analysis+report (same as a single scheduled job)."""
    try:
        do_schedule_once(out_dir=Path(out_dir), sandbox=sandbox)
    except Exception as e:
        raise _exit_for_error(e)


@schedule_app.command("status")
def schedule_status() -> None:
    """Show cron expression and next run time (best-effort)."""
    try:
        status = do_schedule_status()
        console = Console()
        console.print(f"cron: {status.cron}")
        if status.next_run:
            console.print(f"next: {status.next_run}")
        else:
            console.print(f"next: [red]unavailable[/red] ({status.error})")
    except Exception as e:
        raise _exit_for_error(e)


@app.command()
def chat(
    backend: str | None = typer.Option(None, "--backend", help="Override model.backend (auto/ollama/llama_cpp/mlx/transformers/onnx)"),
    model: str | None = typer.Option(None, "--model", help="Model name or identifier (backend-specific)"),
    host: str | None = typer.Option(None, "--host", help="Ollama host URL (when backend=ollama)"),
    path: str | None = typer.Option(None, "--path", help="Local model path (GGUF file for llama.cpp; dir for mlx/transformers)"),
    offline: bool | None = typer.Option(None, "--offline/--no-offline", help="Require local files only"),
    out_dir: str = typer.Option("reports", "--out-dir", help="Output directory for /analyze and /backtest commands"),
) -> None:
    """Start an interactive chat UI using a local model backend."""
    try:
        run_chat(backend=backend, model=model, host=host, path=path, offline=offline, out_dir=out_dir)
    except Exception as e:
        raise _exit_for_error(e)


@llm_app.command("check")
def llm_check(
    backend: str | None = typer.Option(None, "--backend", help="Backend to check (auto/ollama/llama_cpp/mlx/transformers/onnx)"),
    model: str | None = typer.Option(None, "--model", help="Model name or identifier (backend-specific)"),
    host: str | None = typer.Option(None, "--host", help="Ollama host URL (when backend=ollama)"),
    path: str | None = typer.Option(None, "--path", help="Local model path (GGUF file for llama.cpp; dir for mlx/transformers)"),
    offline: bool | None = typer.Option(None, "--offline/--no-offline", help="Require local files only"),
) -> None:
    """Check LLM backend connectivity / availability."""
    try:
        Console().print(
            do_llm_check(
                backend=backend,
                model=model,
                host=host,
                path=path,
                offline=offline,
            )
        )
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("fetch")
def data_fetch(tickers: list[str] = typer.Argument(None)) -> None:
    """Fetch price data for tickers (populates cache)."""
    try:
        fetched = do_data_fetch(tickers if tickers else None)
        Console().print(f"Fetched {len(fetched)} tickers")
    except Exception as e:
        raise _exit_for_error(e)


@data_app.command("verify")
def data_verify(tickers: list[str] = typer.Argument(None)) -> None:
    """Verify data provider(s) for tickers."""
    try:
        results = do_data_verify(tickers if tickers else None)
        for t, status in results.items():
            Console().print(f"{t}: {status}")
    except Exception as e:
        raise _exit_for_error(e)


@report_app.command("open")
def report_open() -> None:
    """Print latest report path (if any)."""
    try:
        p = do_report_open()
        Console().print(str(p))
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("list")
def history_list(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recent runs."""
    try:
        records = do_history_list(limit=limit)
        if not records:
            Console().print("No history")
            return
        for i, r in enumerate(records):
            Console().print(f"{i}: {r.started_at}  {','.join(r.tickers)}  {r.report_path}  {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


@history_app.command("show")
def history_show(index: int = typer.Argument(..., min=0), limit: int = typer.Option(2000, "--limit", min=1, max=2000)) -> None:
    """Show details for a prior run by index (within the last --limit entries)."""
    try:
        r = do_history_show(index, limit=limit)
        Console().print(f"started_at: {r.started_at}")
        Console().print(f"tickers: {','.join(r.tickers)}")
        Console().print(f"report_path: {r.report_path}")
        Console().print(f"json_path: {r.json_path}")
    except Exception as e:
        raise _exit_for_error(e)


def main() -> None:
    app()
