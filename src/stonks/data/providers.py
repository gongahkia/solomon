from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
import requests


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
    def __init__(self, session: requests.Session | None = None, timeout_s: float = 20.0):
        self._session = session or requests.Session()
        self._timeout_s = timeout_s

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        stooq_symbol = normalized.lower()
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
        resp = self._session.get(url, timeout=self._timeout_s)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
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
