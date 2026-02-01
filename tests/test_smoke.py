from __future__ import annotations

from stonks_cli.analysis.indicators import sma


def test_rsi_in_range():
    import pandas as pd

    from stonks_cli.analysis.indicators import rsi

    close = pd.Series([100 + i for i in range(50)])
    out = rsi(close, 14)
    last = float(out.dropna().iloc[-1])
    assert 0.0 <= last <= 100.0


def test_sma_has_expected_length():
    import pandas as pd

    s = pd.Series([1, 2, 3, 4, 5])
    out = sma(s, 3)
    assert len(out) == 5
