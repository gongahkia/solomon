from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from stonks.analysis.strategy import Recommendation


@dataclass(frozen=True)
class TickerResult:
    ticker: str
    last_close: float | None
    recommendation: Recommendation


def write_text_report(results: list[TickerResult], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = out_dir / f"report_{ts}.txt"

    table = Table(title="Stonks Report")
    table.add_column("Ticker", style="cyan")
    table.add_column("Last", justify="right")
    table.add_column("Action", style="magenta")
    table.add_column("Confidence", justify="right")
    table.add_column("Rationale")

    for r in results:
        last = "-" if r.last_close is None else f"{r.last_close:.2f}"
        table.add_row(
            r.ticker,
            last,
            r.recommendation.action,
            f"{r.recommendation.confidence:.2f}",
            r.recommendation.rationale,
        )

    console = Console(record=True, width=120)
    console.print(table)
    path.write_text(console.export_text(), encoding="utf-8")
    return path
