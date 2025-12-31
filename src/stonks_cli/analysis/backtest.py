from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from stonks_cli.analysis.strategy import Recommendation


@dataclass(frozen=True)
class BacktestSeries:
    equity: pd.Series
    position: pd.Series


@dataclass(frozen=True)
class BacktestMetrics:
    cagr: float | None
    sharpe: float | None
    max_drawdown: float | None


def _max_drawdown_from_equity(equity: pd.Series) -> float | None:
    if equity is None or equity.empty:
        return None
    roll_max = equity.cummax()
    dd = (equity / roll_max) - 1.0
    return float(dd.min())


def compute_backtest_metrics(
    equity: pd.Series,
    *,
    periods_per_year: int = 252,
) -> BacktestMetrics:
    if equity is None or equity.empty:
        return BacktestMetrics(cagr=None, sharpe=None, max_drawdown=None)

    total_return = float(equity.iloc[-1] / equity.iloc[0]) if float(equity.iloc[0]) != 0 else float("nan")
    n = max(1, len(equity) - 1)

    cagr = None
    if total_return > 0 and periods_per_year > 0:
        years = n / float(periods_per_year)
        if years > 0:
            cagr = total_return ** (1.0 / years) - 1.0

    rets = equity.pct_change().dropna()
    sharpe = None
    if not rets.empty:
        mean = float(rets.mean())
        std = float(rets.std())
        if std > 0:
            sharpe = (mean / std) * (periods_per_year**0.5)

    mdd = _max_drawdown_from_equity(equity)
    return BacktestMetrics(cagr=cagr, sharpe=sharpe, max_drawdown=mdd)


def _action_to_position(action: str) -> float:
    action = (action or "").upper()
    if action in {"BUY_DCA", "HOLD_DCA"}:
        return 1.0
    if action in {"REDUCE_EXPOSURE"}:
        return 0.0
    if action in {"AVOID_OR_HEDGE", "HOLD_WAIT", "HOLD", "WATCH_REVERSAL", "NO_DATA", "INSUFFICIENT_HISTORY"}:
        return 0.0
    return 0.0


def walk_forward_backtest(
    df: pd.DataFrame,
    *,
    strategy_fn: Callable[[pd.DataFrame], Recommendation],
    min_history_rows: int = 60,
) -> BacktestSeries:
    """Naive walk-forward backtest.

    - Each day t after min_history_rows, compute a recommendation using data up to t.
    - Map the recommendation action to a target position (0 or 1).
    - Apply position(t-1) to close-to-close returns(t) to produce equity.

    Assumes df has a DateTimeIndex (or at least stable order) and a 'close' column.
    """

    if df.empty or "close" not in df.columns:
        equity = pd.Series(dtype=float)
        position = pd.Series(dtype=float)
        return BacktestSeries(equity=equity, position=position)

    close = df["close"].astype(float)
    rets = close.pct_change().fillna(0.0)

    position = pd.Series(0.0, index=df.index)
    for i in range(len(df)):
        if i < min_history_rows:
            position.iloc[i] = 0.0
            continue
        window = df.iloc[: i + 1]
        rec = strategy_fn(window)
        position.iloc[i] = _action_to_position(rec.action)

    strat_rets = rets * position.shift(1).fillna(0.0)
    equity = (1.0 + strat_rets).cumprod()
    return BacktestSeries(equity=equity, position=position)
