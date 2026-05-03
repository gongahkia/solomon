from __future__ import annotations

import pandas as pd

from stonks_cli.analysis.advanced_metrics import compute_advanced_metrics
from stonks_cli.analysis.validation import validate_equity_curve


def test_compute_advanced_metrics_includes_tail_and_benchmark_stats() -> None:
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    equity = pd.Series([1.0 + i * 0.002 for i in range(80)], index=idx)
    benchmark = pd.Series([1.0 + i * 0.001 for i in range(80)], index=idx)

    metrics = compute_advanced_metrics(equity, benchmark_equity=benchmark).to_dict()

    assert metrics["var_95"] is not None
    assert metrics["cvar_95"] is not None
    assert metrics["ulcer_index"] == 0.0
    assert metrics["beta"] is not None
    assert metrics["tracking_error"] is not None


def test_validate_equity_curve_returns_three_validation_blocks() -> None:
    idx = pd.date_range("2025-01-01", periods=80, freq="D")
    equity = pd.Series([1.0 + (i * 0.001) + ((-1) ** i * 0.0002) for i in range(80)], index=idx)

    result = validate_equity_curve(equity, seed=7)

    assert set(result) == {"monte_carlo", "bootstrap_sharpe", "walk_forward"}
    assert result["monte_carlo"]["n_simulations"] == 1000
    assert result["walk_forward"]["consistency_rate"] >= 0.0
