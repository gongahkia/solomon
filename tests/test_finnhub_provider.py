from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from stonks_cli.data.finnhub import FinnhubProvider


@dataclass
class _Resp:
    text: str
    headers: dict

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return json.loads(self.text)


class _Session:
    def __init__(self, text: str, headers: dict | None = None):
        self._text = text
        self._headers = headers or {"X-Ratelimit-Remaining": "10"}
        self.last_url: str | None = None

    def get(self, url: str, headers=None, timeout=None):
        self.last_url = url
        return _Resp(text=self._text, headers=self._headers)

    def mount(self, prefix, adapter):
        pass


@dataclass
class _FakeCfg:
    @dataclass
    class _Keys:
        finnhub_api_key: str = "test-key"

    api_keys: _Keys = None

    def __post_init__(self):
        if self.api_keys is None:
            self.api_keys = self._Keys()


def _make_provider(text: str, tmp_path, headers: dict | None = None) -> tuple[FinnhubProvider, _Session]:
    sess = _Session(text, headers)
    cfg = _FakeCfg()
    p = FinnhubProvider(cfg=cfg, cache_ttl_seconds=0)
    p._session = sess  # inject mock session
    p._cache_dir = tmp_path
    return p, sess


def test_fetch_daily_parses_candle_json(tmp_path):
    payload = json.dumps(
        {
            "s": "ok",
            "t": [1704153600, 1704067200],  # 2024-01-02, 2024-01-01
            "o": [10.0, 9.0],
            "h": [11.0, 10.0],
            "l": [9.0, 8.0],
            "c": [10.5, 9.5],
            "v": [100, 200],
        }
    )
    p, sess = _make_provider(payload, tmp_path)
    series = p.fetch_daily("aapl")
    assert series.ticker == "AAPL.US"  # normalize_ticker applied
    assert sess.last_url is not None and "finnhub.io" in sess.last_url
    df = series.df
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.index) == sorted(df.index)  # sorted
    for col in ("close", "open", "high", "low", "volume"):
        assert col in df.columns


def test_fetch_daily_normalize_ticker(tmp_path):
    payload = json.dumps(
        {
            "s": "ok",
            "t": [1704153600],
            "o": [10.0],
            "h": [11.0],
            "l": [9.0],
            "c": [10.5],
            "v": [100],
        }
    )
    p, _ = _make_provider(payload, tmp_path)
    series = p.fetch_daily("AAPL")
    assert series.ticker == "AAPL.US"


def test_fetch_daily_no_data_returns_empty(tmp_path):
    payload = json.dumps({"s": "no_data"})
    p, _ = _make_provider(payload, tmp_path)
    series = p.fetch_daily("XXXX")
    assert series.df.empty


def test_fetch_daily_invalid_json_returns_empty(tmp_path):
    p, _ = _make_provider("not json at all", tmp_path)
    series = p.fetch_daily("AAPL")
    assert series.df.empty


def test_fetch_daily_missing_t_key_returns_empty(tmp_path):
    payload = json.dumps({"s": "ok", "o": [1]})
    p, _ = _make_provider(payload, tmp_path)
    series = p.fetch_daily("AAPL")
    assert series.df.empty
