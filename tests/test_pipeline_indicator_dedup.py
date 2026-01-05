import io

import pandas as pd
from rich.console import Console

from stonks_cli.config import AppConfig, DataConfig, RiskConfig
from stonks_cli.pipeline import compute_results


def test_pipeline_precomputes_indicators_once_for_builtins(monkeypatch, tmp_path):
    # Create deterministic price history sufficient for SMA cross.
    n = 220
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    close = pd.Series(range(1, n + 1), index=dates, dtype=float)
    df = pd.DataFrame(
        {
            "date": dates,
            "ticker": ["TEST" for _ in range(n)],
            "open": close.values,
            "high": (close + 1).values,
            "low": (close - 1).values,
            "close": close.values,
            "volume": [1000 for _ in range(n)],
        }
    )
    csv_path = tmp_path / "prices.csv"
    df.to_csv(csv_path, index=False)

    cfg = AppConfig(
        tickers=["TEST.US"],
        data=DataConfig(provider="csv", csv_path=str(csv_path), cache_ttl_seconds=0, concurrency_limit=1),
        risk=RiskConfig(min_history_days=60),
        strategy="sma_cross",
        deterministic=True,
    )

    import stonks_cli.analysis.indicators as indicators
    import stonks_cli.analysis.strategy as strategy
    import stonks_cli.pipeline as pipeline

    ind_calls = {"sma": 0}
    pipe_calls = {"sma": 0}
    strat_calls = {"sma": 0}

    orig_ind_sma = indicators.sma
    orig_pipe_sma = pipeline.sma
    orig_strat_sma = strategy.sma

    def ind_sma_wrap(series, window):
        ind_calls["sma"] += 1
        return orig_ind_sma(series, window)

    def pipe_sma_wrap(series, window):
        pipe_calls["sma"] += 1
        return orig_pipe_sma(series, window)

    def strat_sma_wrap(series, window):
        strat_calls["sma"] += 1
        return orig_strat_sma(series, window)

    monkeypatch.setattr(indicators, "sma", ind_sma_wrap)
    monkeypatch.setattr(pipeline, "sma", pipe_sma_wrap)
    monkeypatch.setattr(strategy, "sma", strat_sma_wrap)

    console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
    results, portfolio = compute_results(cfg, console)

    assert len(results) == 1
    assert portfolio is not None

    # SMA cross needs two SMA computations; they should happen in pipeline precompute only.
    assert pipe_calls["sma"] == 2
    assert ind_calls["sma"] == 0
    assert strat_calls["sma"] == 0
