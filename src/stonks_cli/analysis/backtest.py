from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

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
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
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

    position = _vectorized_position_if_supported(df, strategy_fn=strategy_fn, min_history_rows=min_history_rows)
    if position is None:
        position = pd.Series(0.0, index=df.index)
        for i in range(len(df)):
            if i < min_history_rows:
                position.iloc[i] = 0.0
                continue
            window = df.iloc[: i + 1]
            rec = strategy_fn(window)
            position.iloc[i] = _action_to_position(rec.action)

    strat_rets = rets * position.shift(1).fillna(0.0)

    total_cost_bps = float(fee_bps) + float(slippage_bps)
    if total_cost_bps > 0:
        cost_rate = total_cost_bps / 10000.0
        turnover = (position - position.shift(1).fillna(0.0)).abs()
        strat_rets = strat_rets - (turnover * cost_rate)
    equity = (1.0 + strat_rets).cumprod()
    return BacktestSeries(equity=equity, position=position)


def _vectorized_position_if_supported(
    df: pd.DataFrame,
    *,
    strategy_fn: Callable[[pd.DataFrame], Recommendation],
    min_history_rows: int,
) -> pd.Series | None:
    """Best-effort vectorized strategy position.

    Safe for built-in strategies that use only rolling/lagged indicators.
    Falls back to None for unknown/plugin strategies.
    """

    if df is None or df.empty or "close" not in df.columns:
        return None

    from stonks_cli.analysis.indicators import bollinger_bands, rsi, sma
    from stonks_cli.analysis.strategy import (
        basic_trend_rsi_strategy,
        bb_cols,
        mean_reversion_bb_rsi_strategy,
        rsi_col,
        sma_col,
        sma_cross_strategy,
    )

    base_fn = strategy_fn
    kwargs = {}
    if isinstance(strategy_fn, partial):
        base_fn = strategy_fn.func
        kwargs = dict(strategy_fn.keywords or {})

    close = df["close"].astype(float)
    idx = df.index
    pos = pd.Series(0.0, index=idx)

    if base_fn is sma_cross_strategy:
        fast = int(kwargs.get("fast", 20))
        slow = int(kwargs.get("slow", 50))
        eff_min = max(min_history_rows, slow + 2)
        fast_col = sma_col(fast)
        slow_col = sma_col(slow)
        fast_sma = df[fast_col] if fast_col in df.columns else sma(close, fast)
        slow_sma = df[slow_col] if slow_col in df.columns else sma(close, slow)
        uptrend = (fast_sma > slow_sma) & fast_sma.notna() & slow_sma.notna()
        pos.loc[uptrend] = 1.0
        if eff_min > 0 and len(pos) > 0:
            pos.iloc[:eff_min] = 0.0
        return pos

    if base_fn is basic_trend_rsi_strategy:
        sma_fast = int(kwargs.get("sma_fast", 20))
        sma_slow = int(kwargs.get("sma_slow", 50))
        rsi_window = int(kwargs.get("rsi_window", 14))
        rsi_overbought = float(kwargs.get("rsi_overbought", 70))
        min_hist = int(kwargs.get("min_history_days", 60))
        eff_min = max(min_history_rows, min_hist)
        sma_fast_s = df[sma_col(sma_fast)] if sma_col(sma_fast) in df.columns else sma(close, sma_fast)
        sma_slow_s = df[sma_col(sma_slow)] if sma_col(sma_slow) in df.columns else sma(close, sma_slow)
        rsi_s = df[rsi_col(rsi_window)] if rsi_col(rsi_window) in df.columns else rsi(close, rsi_window)
        buy = (
            (sma_fast_s > sma_slow_s)
            & (rsi_s < rsi_overbought)
            & sma_fast_s.notna()
            & sma_slow_s.notna()
            & rsi_s.notna()
        )
        pos.loc[buy] = 1.0
        if eff_min > 0 and len(pos) > 0:
            pos.iloc[:eff_min] = 0.0
        return pos

    if base_fn is mean_reversion_bb_rsi_strategy:
        bb_window = int(kwargs.get("bb_window", 20))
        bb_num_std = float(kwargs.get("bb_num_std", 2.0))
        rsi_window = int(kwargs.get("rsi_window", 14))
        rsi_low = float(kwargs.get("rsi_low", 35))
        min_hist = int(kwargs.get("min_history_days", 60))
        eff_min = max(min_history_rows, min_hist)
        lo_c, _mid_c, _up_c = bb_cols(bb_window, bb_num_std)
        lower = df[lo_c] if lo_c in df.columns else bollinger_bands(close, window=bb_window, num_std=bb_num_std)[0]
        rsi_s = df[rsi_col(rsi_window)] if rsi_col(rsi_window) in df.columns else rsi(close, rsi_window)
        buy = (close < lower) & (rsi_s <= rsi_low) & lower.notna() & rsi_s.notna()
        pos.loc[buy] = 1.0
        if eff_min > 0 and len(pos) > 0:
            pos.iloc[:eff_min] = 0.0
        return pos

    return None
