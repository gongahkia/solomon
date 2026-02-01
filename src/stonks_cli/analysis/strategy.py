from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stonks_cli.analysis.indicators import bollinger_bands, rsi, sma


def sma_col(window: int) -> str:
    return f"sma_{int(window)}"


def rsi_col(window: int) -> str:
    return f"rsi_{int(window)}"


def bb_cols(window: int, num_std: float) -> tuple[str, str, str]:
    std_s = str(float(num_std)).replace(".", "p")
    suf = f"{int(window)}_{std_s}"
    return (f"bb_lower_{suf}", f"bb_mid_{suf}", f"bb_upper_{suf}")


_sma_col = sma_col
_rsi_col = rsi_col
_bb_cols = bb_cols


@dataclass(frozen=True)
class Recommendation:
    action: str
    confidence: float
    rationale: str


def basic_trend_rsi_strategy(
    df: pd.DataFrame,
    *,
    sma_fast: int = 20,
    sma_slow: int = 50,
    rsi_window: int = 14,
    rsi_overbought: float = 70,
    rsi_oversold: float = 30,
    min_history_days: int = 60,
) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")

    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < min_history_days:
        return Recommendation(
            action="INSUFFICIENT_HISTORY",
            confidence=0.1,
            rationale=f"Need >={min_history_days} days",
        )

    fast_col = sma_col(sma_fast)
    slow_col = sma_col(sma_slow)
    rsi_c = rsi_col(rsi_window)
    sma_fast_s = df[fast_col] if fast_col in df.columns else sma(close, sma_fast)
    sma_slow_s = df[slow_col] if slow_col in df.columns else sma(close, sma_slow)
    rsi_s = df[rsi_c] if rsi_c in df.columns else rsi(close, rsi_window)
    sma_fast_v = sma_fast_s.iloc[-1]
    sma_slow_v = sma_slow_s.iloc[-1]
    rsi_v = rsi_s.iloc[-1]
    last = float(close.iloc[-1])

    if pd.isna(sma_fast_v) or pd.isna(sma_slow_v) or pd.isna(rsi_v):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Indicators not ready")

    trend_up = sma_fast_v > sma_slow_v
    overbought = float(rsi_v) >= float(rsi_overbought)
    oversold = float(rsi_v) <= float(rsi_oversold)

    if trend_up and not overbought:
        return Recommendation(
            action="BUY_DCA",
            confidence=0.65,
            rationale=(
                f"Uptrend (SMA{sma_fast} {float(sma_fast_v):.2f} > SMA{sma_slow} {float(sma_slow_v):.2f}) "
                f"and RSI{rsi_window} {float(rsi_v):.1f} not overbought; last={last:.2f}"
            ),
        )
    if trend_up and overbought:
        return Recommendation(
            action="HOLD_WAIT",
            confidence=0.55,
            rationale=f"Uptrend but RSI{rsi_window} {float(rsi_v):.1f} overbought; consider waiting/pacing buys; last={last:.2f}",
        )
    if (not trend_up) and oversold:
        return Recommendation(
            action="WATCH_REVERSAL",
            confidence=0.45,
            rationale=f"Downtrend but RSI{rsi_window} {float(rsi_v):.1f} oversold; watch for reversal; last={last:.2f}",
        )
    return Recommendation(
        action="AVOID_OR_HEDGE",
        confidence=0.6,
        rationale=(
            f"Downtrend (SMA{sma_fast} {float(sma_fast_v):.2f} <= SMA{sma_slow} {float(sma_slow_v):.2f}); "
            f"last={last:.2f}"
        ),
    )


def sma_cross_strategy(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")
    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < (slow + 2):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale=f"Need >={slow + 2} days")

    fast_col = sma_col(fast)
    slow_col = sma_col(slow)
    fast_sma = df[fast_col] if fast_col in df.columns else sma(close, fast)
    slow_sma = df[slow_col] if slow_col in df.columns else sma(close, slow)
    prev_fast, cur_fast = fast_sma.iloc[-2], fast_sma.iloc[-1]
    prev_slow, cur_slow = slow_sma.iloc[-2], slow_sma.iloc[-1]
    last = float(close.iloc[-1])

    if pd.isna(prev_fast) or pd.isna(cur_fast) or pd.isna(prev_slow) or pd.isna(cur_slow):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Indicators not ready")

    crossed_up = (prev_fast <= prev_slow) and (cur_fast > cur_slow)
    crossed_down = (prev_fast >= prev_slow) and (cur_fast < cur_slow)

    if crossed_up:
        return Recommendation(
            action="BUY_DCA",
            confidence=0.7,
            rationale=f"Bullish SMA cross: SMA{fast} crossed above SMA{slow}; last={last:.2f}",
        )
    if crossed_down:
        return Recommendation(
            action="REDUCE_EXPOSURE",
            confidence=0.7,
            rationale=f"Bearish SMA cross: SMA{fast} crossed below SMA{slow}; last={last:.2f}",
        )
    if cur_fast > cur_slow:
        return Recommendation(
            action="HOLD_DCA",
            confidence=0.55,
            rationale=f"Uptrend: SMA{fast} > SMA{slow}; last={last:.2f}",
        )
    return Recommendation(
        action="AVOID_OR_HEDGE",
        confidence=0.55,
        rationale=f"Downtrend: SMA{fast} <= SMA{slow}; last={last:.2f}",
    )


def mean_reversion_bb_rsi_strategy(
    df: pd.DataFrame,
    *,
    bb_window: int = 20,
    bb_num_std: float = 2.0,
    rsi_window: int = 14,
    rsi_low: float = 35,
    rsi_high: float = 65,
    min_history_days: int = 60,
) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")
    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < min_history_days:
        return Recommendation(
            action="INSUFFICIENT_HISTORY",
            confidence=0.1,
            rationale=f"Need >={min_history_days} days",
        )

    lo_c, mid_c, up_c = bb_cols(bb_window, bb_num_std)
    if {lo_c, mid_c, up_c}.issubset(set(df.columns)):
        lower, mid, upper = df[lo_c], df[mid_c], df[up_c]
    else:
        lower, mid, upper = bollinger_bands(close, window=bb_window, num_std=bb_num_std)
    rsi_c = rsi_col(rsi_window)
    rsi14 = df[rsi_c] if rsi_c in df.columns else rsi(close, rsi_window)
    last = float(close.iloc[-1])

    lo, mi, up = lower.iloc[-1], mid.iloc[-1], upper.iloc[-1]
    r = rsi14.iloc[-1]
    if pd.isna(lo) or pd.isna(up) or pd.isna(r):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Indicators not ready")

    if last < float(lo) and float(r) <= float(rsi_low):
        return Recommendation(
            action="BUY_DCA",
            confidence=0.6,
            rationale=f"Price below lower band and RSI{rsi_window} {float(r):.1f} low; last={last:.2f}",
        )
    if last > float(up) and float(r) >= float(rsi_high):
        return Recommendation(
            action="HOLD_WAIT",
            confidence=0.6,
            rationale=f"Price above upper band and RSI{rsi_window} {float(r):.1f} high; last={last:.2f}",
        )
    return Recommendation(
        action="HOLD",
        confidence=0.45,
        rationale=f"Mean reversion signals neutral; last={last:.2f}, mid={float(mi):.2f}",
    )
