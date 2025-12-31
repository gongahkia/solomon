from __future__ import annotations

from stonks.analysis.indicators import sma


def test_sma_has_expected_length():
    import pandas as pd

    s = pd.Series([1, 2, 3, 4, 5])
    out = sma(s, 3)
    assert len(out) == 5
