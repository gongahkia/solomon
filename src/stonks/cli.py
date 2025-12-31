from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from stonks.chat.repl import run_chat
from stonks.config import config_path, load_config, save_default_config
from stonks.pipeline import run_once
from stonks.scheduler.run import run_scheduler

app = typer.Typer(add_completion=True)


@app.command()
def config_init(path: str | None = typer.Option(None, "--path")) -> None:
    """Create a default config file."""
    p = Path(path).expanduser() if path else None
    out = save_default_config(p)
    Console().print(f"Created config: {out}")


@app.command()
def config_show() -> None:
    """Print effective config."""
    cfg = load_config()
    Console().print(cfg.model_dump_json(indent=2))


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


@app.command()
def schedule(
    out_dir: str = typer.Option("reports", "--out-dir"),
) -> None:
    """Run the cron-like scheduler in the foreground."""
    cfg = load_config()
    run_scheduler(cfg, out_dir=Path(out_dir))


@app.command()
def chat() -> None:
    """Start an interactive chat UI using a local model backend."""
    cfg = load_config()
    run_chat(host=cfg.model.host, model=cfg.model.model)


@app.command()
def where_config() -> None:
    """Print config path."""
    Console().print(str(config_path()))


def main() -> None:
    app()
