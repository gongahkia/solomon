from __future__ import annotations

import json
from pathlib import Path

from stonks_cli.analysis.backtest import BacktestMetrics
from stonks_cli.reporting.report import TickerResult


def _metrics_dict(m: BacktestMetrics | None) -> dict | None:
    if m is None:
        return None
    return {
        "cagr": m.cagr,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
    }


def write_json_report(
    results: list[TickerResult],
    *,
    out_path: Path,
    portfolio: BacktestMetrics | None = None,
) -> Path:
    payload = {
        "results": [
            {
                "ticker": r.ticker,
                "last_close": r.last_close,
                "action": r.recommendation.action,
                "confidence": r.recommendation.confidence,
                "rationale": r.recommendation.rationale,
                "rows_used": r.rows_used,
                "last_date": r.last_date,
                "missing_columns": r.missing_columns,
                "suggested_position_fraction": r.suggested_position_fraction,
                "vol_annualized": r.vol_annualized,
                "atr14": r.atr14,
                "stop_loss": r.stop_loss,
                "take_profit": r.take_profit,
                "backtest": _metrics_dict(r.backtest),
            }
            for r in results
        ],
        "portfolio": _metrics_dict(portfolio),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path
