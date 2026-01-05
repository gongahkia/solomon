from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from stonks_cli.analysis.backtest import BacktestMetrics
from stonks_cli.analysis.strategy import Recommendation


@dataclass(frozen=True)
class TickerResult:
    ticker: str
    last_close: float | None
    recommendation: Recommendation
    backtest: BacktestMetrics | None = None
    suggested_position_fraction: float | None = None
    vol_annualized: float | None = None
    atr14: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None


def write_text_report(results: list[TickerResult], out_dir: Path, *, portfolio: BacktestMetrics | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = out_dir / f"report_{ts}.txt"

    table = Table(title="Stonks Report")
    table.add_column("Ticker", style="cyan")
    table.add_column("Last", justify="right")
    table.add_column("Action", style="magenta")
    table.add_column("Confidence", justify="right")
    table.add_column("CAGR", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("Rationale")

    def fmt(v: float | None, *, pct: bool = False) -> str:
        if v is None:
            return "-"
        return f"{v*100:.1f}%" if pct else f"{v:.2f}"

    for r in results:
        last = "-" if r.last_close is None else f"{r.last_close:.2f}"
        table.add_row(
            r.ticker,
            last,
            r.recommendation.action,
            f"{r.recommendation.confidence:.2f}",
            fmt(r.backtest.cagr if r.backtest else None, pct=True),
            fmt(r.backtest.sharpe if r.backtest else None, pct=False),
            fmt(r.backtest.max_drawdown if r.backtest else None, pct=True),
            r.recommendation.rationale,
        )

    console = Console(record=True, width=120)
    console.print("Stonks Report")
    console.print(f"generated_at: {datetime.now().isoformat()}")
    console.print(f"tickers: {len(results)}")
    console.print("")
    console.print(table)

    if portfolio is not None:
        summary = Table(title="Portfolio Backtest")
        summary.add_column("CAGR", justify="right")
        summary.add_column("Sharpe", justify="right")
        summary.add_column("MaxDD", justify="right")
        summary.add_row(
            fmt(portfolio.cagr, pct=True),
            fmt(portfolio.sharpe, pct=False),
            fmt(portfolio.max_drawdown, pct=True),
        )
        console.print(summary)

    console.print("")
    console.print("Risk Notes & Assumptions")
    console.print("- This report is for informational purposes only; it is not financial advice.")
    console.print("- Price data is sourced from the configured provider and may be delayed or incomplete.")
    console.print("- Backtests are simplified and do not include fees, slippage, taxes, or dividends unless present in the data.")
    console.print("- Strategy signals and sizing are heuristic and may not generalize to future market conditions.")

    path.write_text(console.export_text(), encoding="utf-8")
    return path
