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
    rows_used: int | None = None
    last_date: str | None = None
    missing_columns: list[str] | None = None
    suggested_position_fraction: float | None = None
    vol_annualized: float | None = None
    atr14: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    beta: float | None = None
    benchmark: str | None = None


def write_text_report(
    results: list[TickerResult],
    out_dir: Path,
    *,
    portfolio: BacktestMetrics | None = None,
    name: str | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if name:
        n = name
        if not n.lower().endswith(".txt"):
            n = f"{n}.txt"
        path = out_dir / n
    else:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = out_dir / f"report_{ts}.txt"

    # Check if any result has beta
    has_beta = any(r.beta is not None for r in results)
    benchmark_name = next((r.benchmark for r in results if r.benchmark), None)

    table = Table(title="Stonks Report")
    table.add_column("Ticker", style="cyan")
    table.add_column("Last", justify="right")
    table.add_column("Action", style="magenta")
    table.add_column("Confidence", justify="right")
    if has_beta:
        table.add_column(f"Beta ({benchmark_name})" if benchmark_name else "Beta", justify="right")
    table.add_column("CAGR", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD", justify="right")
    table.add_column("Data")
    table.add_column("Rationale")

    def fmt(v: float | None, *, pct: bool = False) -> str:
        if v is None:
            return "-"
        return f"{v * 100:.1f}%" if pct else f"{v:.2f}"

    action_rank = {
        # Positive actions.
        "BUY_DCA": 0,
        # Neutral / watch.
        "HOLD_WAIT": 10,
        "WATCH_REVERSAL": 20,
        # Risk reduction / negative actions.
        "REDUCE_EXPOSURE": 30,
        "AVOID_OR_HEDGE": 40,
        # Data conditions.
        "INSUFFICIENT_HISTORY": 90,
        "NO_DATA": 100,
    }

    def sort_key(r: TickerResult) -> tuple[int, float, str]:
        return (
            int(action_rank.get(r.recommendation.action, 50)),
            -float(r.recommendation.confidence),
            r.ticker,
        )

    for r in sorted(results, key=sort_key):
        last = "-" if r.last_close is None else f"{r.last_close:.2f}"
        data_bits = []
        if r.rows_used is not None:
            data_bits.append(f"n={r.rows_used}")
        if r.last_date:
            data_bits.append(f"last={r.last_date}")
        if r.missing_columns:
            data_bits.append("miss=" + ",".join(r.missing_columns))
        data_summary = " ".join(data_bits) if data_bits else "-"

        row_values = [
            r.ticker,
            last,
            r.recommendation.action,
            f"{r.recommendation.confidence:.2f}",
        ]
        if has_beta:
            row_values.append(fmt(r.beta, pct=False))
        row_values.extend(
            [
                fmt(r.backtest.cagr if r.backtest else None, pct=True),
                fmt(r.backtest.sharpe if r.backtest else None, pct=False),
                fmt(r.backtest.max_drawdown if r.backtest else None, pct=True),
                data_summary,
                r.recommendation.rationale,
            ]
        )
        table.add_row(*row_values)

    console = Console(record=True, width=120)
    console.print("Stonks Report")
    console.print(f"generated_at: {datetime.now().isoformat()}")
    console.print(f"tickers: {len(results)}")

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
    console.print(table)

    console.print("")
    console.print("Risk Notes & Assumptions")
    console.print("- This report is for informational purposes only; it is not financial advice.")
    console.print("- Price data is sourced from the configured provider and may be delayed or incomplete.")
    console.print(
        "- Backtests are simplified and do not include fees, slippage, taxes, or dividends unless present in the data."
    )
    console.print("- Strategy signals and sizing are heuristic and may not generalize to future market conditions.")

    path.write_text(console.export_text(), encoding="utf-8")
    return path
