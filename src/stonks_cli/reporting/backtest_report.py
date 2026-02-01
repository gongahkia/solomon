from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from stonks_cli.analysis.backtest import BacktestMetrics


@dataclass(frozen=True)
class BacktestRow:
    ticker: str
    metrics: BacktestMetrics


def write_backtest_report(rows: list[BacktestRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = out_dir / f"backtest_{ts}.txt"

    table = Table(title="Stonks Backtest")
    table.add_column("Ticker", style="cyan")
    table.add_column("CAGR", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")

    def fmt(v: float | None, *, pct: bool = False) -> str:
        if v is None:
            return "-"
        return f"{v * 100:.1f}%" if pct else f"{v:.2f}"

    for r in rows:
        table.add_row(
            r.ticker,
            fmt(r.metrics.cagr, pct=True),
            fmt(r.metrics.sharpe),
            fmt(r.metrics.max_drawdown, pct=True),
        )

    console = Console(record=True, width=120)
    console.print(table)
    path.write_text(console.export_text(), encoding="utf-8")
    return path
