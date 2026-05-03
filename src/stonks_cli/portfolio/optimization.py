from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

OptimizerMethod = Literal["equal", "equal_volatility", "risk_parity", "mean_variance"]


def optimize_weights(
    prices: pd.DataFrame,
    *,
    method: OptimizerMethod = "risk_parity",
    lookback: int = 60,
) -> dict[str, float]:
    """Return long-only weights from a price matrix with asset columns."""

    if prices is None or prices.empty:
        return {}
    clean = prices.dropna(axis=1, how="all").ffill().dropna(how="any")
    if clean.empty:
        return {}
    if lookback > 0 and len(clean) > lookback:
        clean = clean.tail(lookback)

    returns = clean.pct_change().dropna()
    cols = list(returns.columns)
    if not cols:
        return {}
    if len(cols) == 1 or returns.empty or method == "equal":
        return {cols[0]: 1.0} if len(cols) == 1 else {c: 1.0 / len(cols) for c in cols}

    cov = returns.cov().to_numpy(dtype=float)
    if np.isnan(cov).any():
        return _equal(cols)

    if method == "equal_volatility":
        vols = np.sqrt(np.diag(cov))
        return _weights_to_dict(cols, _inverse_vol_weights(vols))
    if method == "mean_variance":
        mu = returns.mean().to_numpy(dtype=float)
        return _weights_to_dict(cols, _mean_variance_weights(mu, cov))
    if method == "risk_parity":
        return _weights_to_dict(cols, _risk_parity_weights(cov))
    raise ValueError(f"unknown optimizer method: {method}")


def _equal(cols: list[str]) -> dict[str, float]:
    return {c: 1.0 / len(cols) for c in cols} if cols else {}


def _weights_to_dict(cols: list[str], weights: np.ndarray) -> dict[str, float]:
    weights = _normalize(weights)
    return {c: float(w) for c, w in zip(cols, weights, strict=False)}


def _normalize(weights: np.ndarray) -> np.ndarray:
    clean = np.nan_to_num(weights.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    clean = np.clip(clean, 0.0, None)
    total = float(clean.sum())
    if total <= 1e-12:
        return np.ones(len(clean)) / len(clean) if len(clean) else clean
    return clean / total


def _inverse_vol_weights(vols: np.ndarray) -> np.ndarray:
    if np.any(vols <= 1e-12) or np.isnan(vols).any():
        return np.ones(len(vols)) / len(vols)
    inv = 1.0 / vols
    return inv / inv.sum()


def _risk_parity_weights(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    if n == 0:
        return np.array([])
    w = _inverse_vol_weights(np.sqrt(np.diag(cov)))
    for _ in range(50):
        port_var = float(w @ cov @ w)
        if port_var <= 1e-12:
            break
        mrc = cov @ w / np.sqrt(port_var)
        rc = w * mrc
        target = np.sqrt(port_var) / n
        next_w = _normalize(w * (target / (rc + 1e-12)))
        if float(np.max(np.abs(next_w - w))) < 1e-8:
            w = next_w
            break
        w = next_w
    return w


def _mean_variance_weights(mu: np.ndarray, cov: np.ndarray) -> np.ndarray:
    if len(mu) == 0:
        return np.array([])
    try:
        raw = np.linalg.pinv(cov) @ mu
    except np.linalg.LinAlgError:
        return np.ones(len(mu)) / len(mu)
    return _normalize(raw)
