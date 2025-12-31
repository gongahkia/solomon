import pandas as pd

from stonks_cli.analysis.backtest import compute_backtest_metrics, walk_forward_backtest
from stonks_cli.analysis.strategy import Recommendation


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
