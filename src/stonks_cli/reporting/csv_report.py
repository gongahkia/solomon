from __future__ import annotations

import csv
from pathlib import Path

from stonks_cli.reporting.report import TickerResult


def write_csv_summary(results: list[TickerResult], *, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["ticker", "action", "confidence", "cagr", "sharpe", "maxdd"],
            lineterminator="\n",
        )
        writer.writeheader()
        for r in results:
            metrics = r.backtest
            writer.writerow(
                {
                    "ticker": r.ticker,
                    "action": r.recommendation.action,
                    "confidence": f"{r.recommendation.confidence:.4f}",
                    "cagr": "" if metrics is None or metrics.cagr is None else f"{metrics.cagr:.6f}",
                    "sharpe": "" if metrics is None or metrics.sharpe is None else f"{metrics.sharpe:.6f}",
                    "maxdd": "" if metrics is None or metrics.max_drawdown is None else f"{metrics.max_drawdown:.6f}",
                }
            )

    return out_path
