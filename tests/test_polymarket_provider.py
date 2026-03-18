from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from stonks_cli.data.polymarket import PolymarketProvider


@dataclass
class _Resp:
    text: str
    def raise_for_status(self) -> None:
        return None


class _Session:
    """Mock session that routes by URL prefix."""
    def __init__(self, gamma_text: str, clob_text: str):
        self._gamma_text = gamma_text
        self._clob_text = clob_text
        self.last_url: str | None = None

    def get(self, url: str, params=None, timeout: float = 20.0):
        self.last_url = url
        if "gamma-api" in url:
            return _Resp(text=self._gamma_text)
        return _Resp(text=self._clob_text) # clob


def _make_gamma(condition_id: str = "0xabc123") -> str:
    return json.dumps([{"condition_id": condition_id, "slug": "test-market"}])


def _make_history(prices: list[tuple[int, float]] | None = None) -> str:
    if prices is None:
        prices = [(1700000000, 0.45), (1700086400, 0.52), (1700172800, 0.61)]
    return json.dumps({"history": [{"t": t, "p": p} for t, p in prices]})


def test_fetch_daily_returns_date_close(tmp_path):
    sess = _Session(_make_gamma(), _make_history())
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:test-market")
    df = series.df
    assert not df.empty
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.columns) == ["close"]
    assert df.index.name == "date"


def test_prefix_stripped(tmp_path):
    sess = _Session(_make_gamma(), _make_history())
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:test-market")
    assert series.ticker == "POLYMARKET:TEST-MARKET" # normalized upper, no .US
    assert sess.last_url is not None


def test_no_prefix_works(tmp_path):
    sess = _Session(_make_gamma(), _make_history())
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("test-market")
    assert not series.df.empty


def test_empty_gamma_response_returns_empty_df(tmp_path):
    sess = _Session(json.dumps([]), _make_history())
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:nonexistent")
    assert series.df.empty


def test_invalid_json_returns_empty_df(tmp_path):
    sess = _Session("not json", "also not json")
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:bad")
    assert series.df.empty


def test_close_values_between_0_and_1(tmp_path):
    prices = [(1700000000, 0.0), (1700086400, 0.5), (1700172800, 1.0)]
    sess = _Session(_make_gamma(), _make_history(prices))
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:bounded-market")
    df = series.df
    assert (df["close"] >= 0).all()
    assert (df["close"] <= 1).all()


def test_dates_sorted(tmp_path):
    prices = [(1700172800, 0.7), (1700000000, 0.3), (1700086400, 0.5)] # out of order
    sess = _Session(_make_gamma(), _make_history(prices))
    p = PolymarketProvider(session=sess, cache_dir=tmp_path, cache_ttl_seconds=0)
    series = p.fetch_daily("POLYMARKET:sort-test")
    df = series.df
    assert list(df.index) == sorted(df.index)
