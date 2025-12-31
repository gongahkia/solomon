from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stonks.data.providers import StooqProvider


@dataclass
class _Resp:
    text: str

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, text: str):
        self._text = text
        self.last_url: str | None = None

    def get(self, url: str, timeout: float):
        self.last_url = url
        return _Resp(text=self._text)


def test_stooq_provider_parses_and_sorts_dates(tmp_path):
    csv = """Date,Open,High,Low,Close,Volume
2025-01-03,10,11,9,10.5,100
2025-01-02,9,10,8,9.5,200
"""
    sess = _Session(csv)
    p = StooqProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)

    series = p.fetch_daily("aapl")
    assert series.ticker == "AAPL.US"
    assert sess.last_url is not None and "stooq.com" in sess.last_url

    df = series.df
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.index) == sorted(df.index)
    assert "close" in df.columns
    assert float(df.loc[pd.Timestamp("2025-01-02"), "close"]) == 9.5
