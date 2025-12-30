from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

from stonks.data.cache import default_cache_dir, load_cached_text, save_cached_text


def normalize_ticker(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        raise ValueError("Ticker cannot be empty")
    t = raw.upper()
    # Minimal convenience: if user provides no exchange suffix, default to US.
    # Example: AAPL -> AAPL.US
    if "." not in t:
        t = f"{t}.US"
    return t


@dataclass(frozen=True)
class PriceSeries:
    ticker: str
    df: pd.DataFrame


class PriceProvider:
    def fetch_daily(self, ticker: str) -> PriceSeries:  # pragma: no cover
        raise NotImplementedError


class StooqProvider(PriceProvider):
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_s: float = 20.0,
        cache_dir: Path | None = None,
        cache_ttl_seconds: int = 3600,
    ):
        self._session = session or requests.Session()
        self._timeout_s = timeout_s
        self._cache_dir = cache_dir or default_cache_dir()
        self._cache_ttl_seconds = cache_ttl_seconds

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        stooq_symbol = normalized.lower()
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
        cache_key = f"stooq:daily:{stooq_symbol}"
        text = load_cached_text(self._cache_dir, cache_key, ttl_seconds=self._cache_ttl_seconds)
        if text is None:
            resp = self._session.get(url, timeout=self._timeout_s)
            resp.raise_for_status()
            text = resp.text
            save_cached_text(self._cache_dir, cache_key, text)

        df = pd.read_csv(io.StringIO(text))
        df.columns = [c.strip().lower() for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=False)
            df = df.set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)


class CsvProvider(PriceProvider):
    def __init__(self, csv_path: str):
        self._path = csv_path

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        df = pd.read_csv(self._path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "ticker" in df.columns:
            df = df[df["ticker"].astype(str).str.upper() == normalized]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=False)
            df = df.set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)
