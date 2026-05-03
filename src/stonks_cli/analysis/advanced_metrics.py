from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdvancedMetrics:
    var_95: float | None
    var_99: float | None
    cvar_95: float | None
    cvar_99: float | None
    ulcer_index: float | None
    omega_ratio: float | None
    tail_ratio: float | None
    skewness: float | None
    kurtosis: float | None
    beta: float | None
    alpha: float | None
    tracking_error: float | None
    information_ratio: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "var_95": self.var_95,
            "var_99": self.var_99,
            "cvar_95": self.cvar_95,
            "cvar_99": self.cvar_99,
            "ulcer_index": self.ulcer_index,
            "omega_ratio": self.omega_ratio,
            "tail_ratio": self.tail_ratio,
            "skewness": self.skewness,
            "kurtosis": self.kurtosis,
            "beta": self.beta,
            "alpha": self.alpha,
            "tracking_error": self.tracking_error,
            "information_ratio": self.information_ratio,
        }


def _clean_returns(equity: pd.Series) -> pd.Series:
    if equity is None or equity.empty:
        return pd.Series(dtype=float)
    rets = equity.astype(float).pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    return rets


def _drawdowns(equity: pd.Series) -> pd.Series:
    if equity is None or equity.empty:
        return pd.Series(dtype=float)
    clean = equity.astype(float).dropna()
    if clean.empty:
        return pd.Series(dtype=float)
    peak = clean.cummax().replace(0.0, np.nan)
    return (clean / peak - 1.0).replace([np.inf, -np.inf], np.nan).dropna()


def compute_advanced_metrics(
    equity: pd.Series,
    *,
    benchmark_equity: pd.Series | None = None,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.0,
) -> AdvancedMetrics:
    """Compute institutional-style risk and benchmark metrics from an equity curve."""

    returns = _clean_returns(equity)
    if len(returns) < 2:
        return AdvancedMetrics(
            var_95=None,
            var_99=None,
            cvar_95=None,
            cvar_99=None,
            ulcer_index=None,
            omega_ratio=None,
            tail_ratio=None,
            skewness=None,
            kurtosis=None,
            beta=None,
            alpha=None,
            tracking_error=None,
            information_ratio=None,
        )

    arr = returns.to_numpy(dtype=float)
    var_95 = float(np.percentile(arr, 5))
    var_99 = float(np.percentile(arr, 1))
    cvar_95 = float(arr[arr <= var_95].mean()) if np.any(arr <= var_95) else var_95
    cvar_99 = float(arr[arr <= var_99].mean()) if np.any(arr <= var_99) else var_99

    dd = _drawdowns(equity)
    ulcer_index = float(np.sqrt(np.mean(np.square(dd.to_numpy(dtype=float) * 100.0)))) if not dd.empty else None

    daily_rf = float(risk_free_rate) / float(periods_per_year) if periods_per_year > 0 else 0.0
    excess = arr - daily_rf
    gains = excess[excess > 0].sum()
    losses = -excess[excess < 0].sum()
    omega_ratio = float(gains / losses) if losses > 1e-12 else None

    p95 = float(np.percentile(arr, 95))
    p5 = float(np.percentile(arr, 5))
    tail_ratio = float(abs(p95 / p5)) if abs(p5) > 1e-12 else None

    std = float(np.std(arr, ddof=1))
    if std > 1e-12:
        mean = float(np.mean(arr))
        centered = arr - mean
        skewness = float(np.mean(centered**3) / (std**3))
        kurtosis = float(np.mean(centered**4) / (std**4) - 3.0)
    else:
        skewness = 0.0
        kurtosis = 0.0

    beta = alpha = tracking_error = information_ratio = None
    if benchmark_equity is not None:
        bench_returns = _clean_returns(benchmark_equity)
        aligned = pd.DataFrame({"asset": returns, "benchmark": bench_returns}).dropna()
        if len(aligned) >= 2:
            asset = aligned["asset"]
            bench = aligned["benchmark"]
            bench_var = float(bench.var())
            if bench_var > 1e-12:
                beta = float(asset.cov(bench) / bench_var)
                alpha = float((asset.mean() - daily_rf - beta * (bench.mean() - daily_rf)) * periods_per_year)
            active = asset - bench
            active_std = float(active.std())
            if active_std > 1e-12:
                tracking_error = float(active_std * np.sqrt(periods_per_year))
                information_ratio = float(active.mean() * periods_per_year / tracking_error)

    return AdvancedMetrics(
        var_95=var_95,
        var_99=var_99,
        cvar_95=cvar_95,
        cvar_99=cvar_99,
        ulcer_index=ulcer_index,
        omega_ratio=omega_ratio,
        tail_ratio=tail_ratio,
        skewness=skewness,
        kurtosis=kurtosis,
        beta=beta,
        alpha=alpha,
        tracking_error=tracking_error,
        information_ratio=information_ratio,
    )
