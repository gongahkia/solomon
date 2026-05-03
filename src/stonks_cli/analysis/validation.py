from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def monte_carlo_permutation_test(
    equity: pd.Series,
    *,
    n_simulations: int = 1000,
    periods_per_year: int = 252,
    seed: int = 42,
) -> dict[str, Any]:
    """Shuffle realized returns to estimate how unusual the observed Sharpe is."""

    returns = equity.astype(float).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 5:
        return {"error": "need at least 5 return observations", "p_value_sharpe": 1.0}

    arr = returns.to_numpy(dtype=float)
    actual = _sharpe(arr, periods_per_year)
    rng = np.random.default_rng(seed)
    simulated: list[float] = []
    count_ge = 0
    for _ in range(max(1, n_simulations)):
        candidate = _sharpe(rng.permutation(arr), periods_per_year)
        simulated.append(candidate)
        if candidate >= actual:
            count_ge += 1

    sim = np.array(simulated)
    return {
        "actual_sharpe": round(actual, 4),
        "p_value_sharpe": round(count_ge / len(simulated), 4),
        "simulated_sharpe_mean": round(float(sim.mean()), 4),
        "simulated_sharpe_p5": round(float(np.percentile(sim, 5)), 4),
        "simulated_sharpe_p95": round(float(np.percentile(sim, 95)), 4),
        "n_simulations": len(simulated),
    }


def bootstrap_sharpe_ci(
    equity: pd.Series,
    *,
    n_bootstrap: int = 1000,
    confidence: float = 0.95,
    periods_per_year: int = 252,
    seed: int = 42,
) -> dict[str, Any]:
    returns = equity.astype(float).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 5:
        return {"error": "need at least 5 return observations"}

    arr = returns.to_numpy(dtype=float)
    observed = _sharpe(arr, periods_per_year)
    rng = np.random.default_rng(seed)
    samples = np.array(
        [_sharpe(rng.choice(arr, size=len(arr), replace=True), periods_per_year) for _ in range(max(1, n_bootstrap))]
    )
    alpha = (1.0 - confidence) / 2.0
    return {
        "observed_sharpe": round(observed, 4),
        "ci_lower": round(float(np.percentile(samples, alpha * 100.0)), 4),
        "ci_upper": round(float(np.percentile(samples, (1.0 - alpha) * 100.0)), 4),
        "median_sharpe": round(float(np.median(samples)), 4),
        "prob_positive": round(float(np.mean(samples > 0.0)), 4),
        "confidence": confidence,
        "n_bootstrap": int(len(samples)),
    }


def walk_forward_consistency(
    equity: pd.Series,
    *,
    windows: int = 5,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    if equity is None or len(equity) < windows * 2:
        return {"error": f"need at least {windows * 2} equity points"}

    clean = equity.astype(float).dropna()
    window_size = len(clean) // windows
    rows: list[dict[str, Any]] = []
    for i in range(windows):
        start_i = i * window_size
        end_i = (i + 1) * window_size if i < windows - 1 else len(clean)
        part = clean.iloc[start_i:end_i]
        returns = part.pct_change().dropna().to_numpy(dtype=float)
        total_return = float(part.iloc[-1] / part.iloc[0] - 1.0) if float(part.iloc[0]) != 0 else 0.0
        drawdown = (part / part.cummax().replace(0.0, np.nan) - 1.0).dropna()
        rows.append(
            {
                "window": i + 1,
                "start": str(part.index[0].date()) if hasattr(part.index[0], "date") else str(part.index[0]),
                "end": str(part.index[-1].date()) if hasattr(part.index[-1], "date") else str(part.index[-1]),
                "return": round(total_return, 6),
                "sharpe": round(_sharpe(returns, periods_per_year), 4) if len(returns) >= 2 else 0.0,
                "max_drawdown": round(float(drawdown.min()), 6) if not drawdown.empty else 0.0,
            }
        )

    returns_list = [float(r["return"]) for r in rows]
    profitable = sum(1 for r in returns_list if r > 0)
    return {
        "windows": rows,
        "profitable_windows": profitable,
        "consistency_rate": round(profitable / windows, 4),
        "return_mean": round(float(np.mean(returns_list)), 6),
        "return_std": round(float(np.std(returns_list)), 6),
    }


def validate_equity_curve(equity: pd.Series, *, seed: int = 42) -> dict[str, Any]:
    return {
        "monte_carlo": monte_carlo_permutation_test(equity, seed=seed),
        "bootstrap_sharpe": bootstrap_sharpe_ci(equity, seed=seed),
        "walk_forward": walk_forward_consistency(equity),
    }


def _sharpe(returns: np.ndarray, periods_per_year: int) -> float:
    if len(returns) == 0:
        return 0.0
    std = float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
    if std <= 1e-12:
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(periods_per_year))
