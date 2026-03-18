from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pandas as pd
import pytest


# --- mock tigeropen SDK ---
class _BarPeriod:
    DAY = "day"

class _Language:
    en_US = "en_US"

class _FakeConsts:
    BarPeriod = _BarPeriod
    Language = _Language

class _FakeConfig:
    def __init__(self, sandbox_debug=False):
        self.tiger_id = None
        self.account = None
        self.private_key = None
        self.language = None

class _FakeTigerOpenConfig:
    TigerOpenClientConfig = _FakeConfig

@dataclass
class _Bar:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class _FakeQuoteClient:
    def __init__(self, config):
        self._config = config
        self._bars: list[_Bar] | None = None
    def get_bars(self, symbols, period, begin_time, end_time, limit):
        return self._bars

class _FakeQuoteModule:
    QuoteClient = _FakeQuoteClient


def _install_tiger_mocks():
    """Inject fake tigeropen modules into sys.modules."""
    mods = {
        "tigeropen": types.ModuleType("tigeropen"),
        "tigeropen.common": types.ModuleType("tigeropen.common"),
        "tigeropen.common.consts": types.ModuleType("tigeropen.common.consts"),
        "tigeropen.tiger_open_config": types.ModuleType("tigeropen.tiger_open_config"),
        "tigeropen.quote": types.ModuleType("tigeropen.quote"),
        "tigeropen.quote.quote_client": types.ModuleType("tigeropen.quote.quote_client"),
    }
    mods["tigeropen.common.consts"].BarPeriod = _BarPeriod
    mods["tigeropen.common.consts"].Language = _Language
    mods["tigeropen.tiger_open_config"].TigerOpenClientConfig = _FakeConfig
    mods["tigeropen.quote.quote_client"].QuoteClient = _FakeQuoteClient
    for k, v in mods.items():
        sys.modules[k] = v
    return mods


def _make_cfg(tmp_path):
    """Build a minimal cfg object with api_keys for TigerProvider."""
    key_file = tmp_path / "rsa_key.pem"
    key_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----")
    @dataclass
    class _ApiKeys:
        tiger_id: str = "test_id"
        tiger_account: str = "test_account"
        tiger_private_key_path: str = str(key_file)
        finnhub_api_key: str | None = None
        alpaca_api_key: str | None = None
        alpaca_secret_key: str | None = None
        alpaca_paper: bool = True
    @dataclass
    class _Cfg:
        api_keys: _ApiKeys = None # type: ignore
        def __post_init__(self):
            if self.api_keys is None:
                self.api_keys = _ApiKeys()
    return _Cfg()


@pytest.fixture(autouse=True)
def _patch_tiger_sdk():
    saved = {}
    keys = [k for k in sys.modules if k.startswith("tigeropen")]
    for k in keys:
        saved[k] = sys.modules.pop(k)
    _install_tiger_mocks()
    yield
    for k in list(sys.modules):
        if k.startswith("tigeropen"):
            del sys.modules[k]
    sys.modules.update(saved)


def test_fetch_daily_returns_price_series(tmp_path):
    from stonks_cli.data.tiger import TigerProvider
    cfg = _make_cfg(tmp_path)
    provider = TigerProvider(cfg=cfg)
    client = provider._get_client()
    client._bars = [
        _Bar(time="2025-01-03", open=10, high=11, low=9, close=10.5, volume=100),
        _Bar(time="2025-01-02", open=9, high=10, low=8, close=9.5, volume=200),
    ]
    provider._client = client
    series = provider.fetch_daily("aapl")
    assert series.ticker == "AAPL.US" # normalize_ticker applied
    df = series.df
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.index) == sorted(df.index)
    for col in ("open", "high", "low", "close", "volume"):
        assert col in df.columns
    assert float(df.loc[pd.Timestamp("2025-01-02"), "close"]) == 9.5


def test_fetch_daily_empty_response(tmp_path):
    from stonks_cli.data.tiger import TigerProvider
    cfg = _make_cfg(tmp_path)
    provider = TigerProvider(cfg=cfg)
    client = provider._get_client()
    client._bars = []
    provider._client = client
    series = provider.fetch_daily("MSFT")
    assert series.ticker == "MSFT.US"
    assert series.df.empty


def test_missing_config_raises():
    from stonks_cli.data.tiger import TigerProvider
    with pytest.raises(ValueError):
        TigerProvider(cfg=None)
