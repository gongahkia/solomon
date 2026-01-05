from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stonks_cli.analysis.indicators import bollinger_bands, rsi, sma


@dataclass(frozen=True)
class Recommendation:
    action: str
    confidence: float
    rationale: str


def basic_trend_rsi_strategy(df: pd.DataFrame) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")

    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < 60:
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Need >=60 days")

    sma20_s = df["sma_20"] if "sma_20" in df.columns else sma(close, 20)
    sma50_s = df["sma_50"] if "sma_50" in df.columns else sma(close, 50)
    rsi14_s = df["rsi_14"] if "rsi_14" in df.columns else rsi(close, 14)
    sma20 = sma20_s.iloc[-1]
    sma50 = sma50_s.iloc[-1]
    rsi14 = rsi14_s.iloc[-1]
    last = float(close.iloc[-1])

    if pd.isna(sma20) or pd.isna(sma50) or pd.isna(rsi14):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Indicators not ready")

    trend_up = sma20 > sma50
    overbought = rsi14 >= 70
    oversold = rsi14 <= 30

    if trend_up and not overbought:
        return Recommendation(
            action="BUY_DCA",
            confidence=0.65,
            rationale=f"Uptrend (SMA20 {sma20:.2f} > SMA50 {sma50:.2f}) and RSI {rsi14:.1f} not overbought; last={last:.2f}",
        )
    if trend_up and overbought:
        return Recommendation(
            action="HOLD_WAIT",
            confidence=0.55,
            rationale=f"Uptrend but RSI {rsi14:.1f} overbought; consider waiting/pacing buys; last={last:.2f}",
        )
    if (not trend_up) and oversold:
        return Recommendation(
            action="WATCH_REVERSAL",
            confidence=0.45,
            rationale=f"Downtrend but RSI {rsi14:.1f} oversold; watch for reversal; last={last:.2f}",
        )
    return Recommendation(
        action="AVOID_OR_HEDGE",
        confidence=0.6,
        rationale=f"Downtrend (SMA20 {sma20:.2f} <= SMA50 {sma50:.2f}); last={last:.2f}",
    )


def sma_cross_strategy(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")
    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < (slow + 2):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale=f"Need >={slow+2} days")

    fast_col = f"sma_{fast}"
    slow_col = f"sma_{slow}"
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


def mean_reversion_bb_rsi_strategy(df: pd.DataFrame) -> Recommendation:
    if df.empty:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="No rows")
    close = df["close"] if "close" in df.columns else None
    if close is None:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="Missing close")
    if len(close) < 60:
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Need >=60 days")

    if {"bb_lower_20_2", "bb_mid_20_2", "bb_upper_20_2"}.issubset(set(df.columns)):
        lower, mid, upper = df["bb_lower_20_2"], df["bb_mid_20_2"], df["bb_upper_20_2"]
    else:
        lower, mid, upper = bollinger_bands(close, window=20, num_std=2.0)
    rsi14 = df["rsi_14"] if "rsi_14" in df.columns else rsi(close, 14)
    last = float(close.iloc[-1])

    lo, mi, up = lower.iloc[-1], mid.iloc[-1], upper.iloc[-1]
    r = rsi14.iloc[-1]
    if pd.isna(lo) or pd.isna(up) or pd.isna(r):
        return Recommendation(action="INSUFFICIENT_HISTORY", confidence=0.1, rationale="Indicators not ready")

    if last < float(lo) and float(r) <= 35:
        return Recommendation(
            action="BUY_DCA",
            confidence=0.6,
            rationale=f"Price below lower band and RSI {float(r):.1f} low; last={last:.2f}",
        )
    if last > float(up) and float(r) >= 65:
        return Recommendation(
            action="HOLD_WAIT",
            confidence=0.6,
            rationale=f"Price above upper band and RSI {float(r):.1f} high; last={last:.2f}",
        )
    return Recommendation(
        action="HOLD",
        confidence=0.45,
        rationale=f"Mean reversion signals neutral; last={last:.2f}, mid={float(mi):.2f}",
    )
