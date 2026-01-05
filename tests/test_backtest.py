import pandas as pd
from functools import partial

from stonks_cli.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
from stonks_cli.analysis.strategy import Recommendation, sma_cross_strategy


def test_walk_forward_backtest_equity_grows_on_uptrend() -> None:
    idx = pd.date_range("2025-01-01", periods=200, freq="D")
    df = pd.DataFrame({"close": pd.Series(range(1, 201), index=idx, dtype=float)})

    def always_buy(_: pd.DataFrame) -> Recommendation:
        return Recommendation(action="BUY_DCA", confidence=1.0, rationale="")

    out = walk_forward_backtest(df, strategy_fn=always_buy, min_history_rows=10)
    assert not out.equity.empty
    assert float(out.equity.iloc[-1]) > 1.0


def test_walk_forward_backtest_empty() -> None:
    def noop(_: pd.DataFrame) -> Recommendation:
        return Recommendation(action="NO_DATA", confidence=0.0, rationale="")

    out = walk_forward_backtest(pd.DataFrame(), strategy_fn=noop)
    assert out.equity.empty


def test_compute_backtest_metrics_basic() -> None:
    equity = pd.Series([1.0, 1.01, 1.02, 1.03])
    m = compute_backtest_metrics(equity, periods_per_year=252)
    assert m.cagr is not None
    assert m.max_drawdown == 0.0


def test_walk_forward_backtest_sma_cross_matches_naive() -> None:
    idx = pd.date_range("2025-01-01", periods=220, freq="D")
    close = pd.Series(range(1, 221), index=idx, dtype=float)
    df = pd.DataFrame({"close": close})

    out_vec = walk_forward_backtest(df, strategy_fn=sma_cross_strategy, min_history_rows=60)

    def naive(df_in: pd.DataFrame, min_history_rows: int = 60):
        position = pd.Series(0.0, index=df_in.index)
        for i in range(len(df_in)):
            if i < min_history_rows:
                continue
            window = df_in.iloc[: i + 1]
            rec = sma_cross_strategy(window)
            position.iloc[i] = 1.0 if rec.action in {"BUY_DCA", "HOLD_DCA"} else 0.0
        rets = df_in["close"].pct_change().fillna(0.0)
        equity = (1.0 + (rets * position.shift(1).fillna(0.0))).cumprod()
        return equity

    equity_naive = naive(df, 60)
    assert float(out_vec.equity.iloc[-1]) == float(equity_naive.iloc[-1])


def test_walk_forward_backtest_sma_cross_matches_naive_non_default_params() -> None:
    idx = pd.date_range("2025-01-01", periods=220, freq="D")
    close = pd.Series(range(1, 221), index=idx, dtype=float)
    df = pd.DataFrame({"close": close})

    strat = partial(sma_cross_strategy, fast=10, slow=30)
    out_vec = walk_forward_backtest(df, strategy_fn=strat, min_history_rows=60)

    def naive(df_in: pd.DataFrame, min_history_rows: int = 60):
        position = pd.Series(0.0, index=df_in.index)
        for i in range(len(df_in)):
            if i < min_history_rows:
                continue
            window = df_in.iloc[: i + 1]
            rec = sma_cross_strategy(window, fast=10, slow=30)
            position.iloc[i] = 1.0 if rec.action in {"BUY_DCA", "HOLD_DCA"} else 0.0
        rets = df_in["close"].pct_change().fillna(0.0)
        equity = (1.0 + (rets * position.shift(1).fillna(0.0))).cumprod()
        return equity

    equity_naive = naive(df, 60)
    assert float(out_vec.equity.iloc[-1]) == float(equity_naive.iloc[-1])


def test_walk_forward_backtest_applies_fee_and_slippage_costs() -> None:
    idx = pd.date_range("2025-01-01", periods=120, freq="D")
    close = pd.Series(range(1, 121), index=idx, dtype=float)
    df = pd.DataFrame({"close": close})

    def always_buy(_: pd.DataFrame) -> Recommendation:
        return Recommendation(action="BUY_DCA", confidence=1.0, rationale="")

    no_cost = walk_forward_backtest(df, strategy_fn=always_buy, min_history_rows=10, fee_bps=0.0, slippage_bps=0.0)
    with_cost = walk_forward_backtest(df, strategy_fn=always_buy, min_history_rows=10, fee_bps=5.0, slippage_bps=5.0)

    assert float(with_cost.equity.iloc[-1]) < float(no_cost.equity.iloc[-1])
