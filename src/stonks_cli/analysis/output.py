from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from stonks_cli.analysis.backtest import BacktestMetrics
from stonks_cli.reporting.report import TickerResult


@dataclass(frozen=True)
class AnalysisArtifacts:
    report_path: Path
    json_path: Path | None
    portfolio: BacktestMetrics | None
    results: list[TickerResult]
