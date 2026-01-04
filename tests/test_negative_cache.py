from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stonks_cli.data.providers import StooqProvider


@dataclass
class _Resp:
    text: str

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def get(self, url: str, timeout: float):
        self.calls += 1
        return _Resp(text=self._text)


def test_stooq_negative_cache_avoids_repeated_fetch(tmp_path):
    # Empty response should be treated as negative and cached briefly.
    sess = _Session("")
    p = StooqProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=3600)

    s1 = p.fetch_daily("AAPL")
    assert isinstance(s1.df, pd.DataFrame)
    assert s1.df.empty
    assert sess.calls == 1

    # Second call should not hit the session due to negative cache.
    s2 = p.fetch_daily("AAPL")
    assert s2.df.empty
    assert sess.calls == 1
