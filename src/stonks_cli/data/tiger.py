from __future__ import annotations

import importlib

import pandas as pd

from stonks_cli.data.providers import PriceProvider, PriceSeries, normalize_ticker


class TigerProvider(PriceProvider):
    """Tiger Brokers provider via tigeropen SDK."""

    def __init__(self, cfg=None):
        self._client = None
        if cfg is None or cfg.api_keys is None:
            raise ValueError(
                "TigerProvider requires cfg with api_keys (tiger_id, tiger_account, tiger_private_key_path)"
            )
        keys = cfg.api_keys
        if not keys.tiger_id or not keys.tiger_account or not keys.tiger_private_key_path:
            raise ValueError("TigerProvider requires tiger_id, tiger_account, and tiger_private_key_path in api_keys")
        self._tiger_id = keys.tiger_id
        self._account = keys.tiger_account
        self._private_key_path = keys.tiger_private_key_path

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            tiger_common = importlib.import_module("tigeropen.common.consts")
            tiger_config = importlib.import_module("tigeropen.tiger_open_config")
            quote_mod = importlib.import_module("tigeropen.quote.quote_client")
        except ImportError as e:
            raise ImportError("tigeropen SDK required: pip install tigeropen") from e
        config = tiger_config.TigerOpenClientConfig(sandbox_debug=False)
        config.tiger_id = self._tiger_id
        config.account = self._account
        config.private_key = self._read_private_key()
        config.language = tiger_common.Language.en_US
        self._client = quote_mod.QuoteClient(config)
        return self._client

    def _read_private_key(self) -> str:
        from pathlib import Path

        p = Path(self._private_key_path).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"Tiger RSA private key not found: {p}")
        return p.read_text(encoding="utf-8").strip()

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0]  # strip exchange suffix for Tiger API
        client = self._get_client()
        try:
            bar_period = importlib.import_module("tigeropen.common.consts").BarPeriod
        except ImportError as e:
            raise ImportError("tigeropen SDK required: pip install tigeropen") from e
        bars = client.get_bars(
            symbols=[base_ticker],
            period=bar_period.DAY,
            begin_time=-1,
            end_time=-1,
            limit=5000,
        )
        if bars is None or (hasattr(bars, "empty") and bars.empty) or len(bars) == 0:
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        if isinstance(bars, pd.DataFrame):
            df = bars.copy()
        else:  # list of bar objects
            df = pd.DataFrame(
                [
                    {
                        "date": getattr(b, "time", None),
                        "open": getattr(b, "open", None),
                        "high": getattr(b, "high", None),
                        "low": getattr(b, "low", None),
                        "close": getattr(b, "close", None),
                        "volume": getattr(b, "volume", None),
                    }
                    for b in bars
                ]
            )
        df.columns = [c.strip().lower() for c in df.columns]
        if "time" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"time": "date"})
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=False)
            df = df.set_index("date").sort_index()
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        if keep:
            df = df[keep]
        return PriceSeries(ticker=normalized, df=df)
