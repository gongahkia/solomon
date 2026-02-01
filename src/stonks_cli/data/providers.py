from __future__ import annotations

import importlib
import io
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text


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
        if session is None:
            retry = Retry(
                total=4,
                connect=4,
                read=4,
                status=4,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        self._timeout_s = timeout_s
        self._cache_dir = cache_dir or default_cache_dir()
        self._cache_ttl_seconds = cache_ttl_seconds

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        stooq_symbol = normalized.lower()
        url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
        cache_key = f"stooq:daily:{stooq_symbol}"
        neg_cache_key = f"{cache_key}:neg"
        negative_ttl_seconds = 300

        if self._cache_ttl_seconds > 0:
            neg = load_cached_text(self._cache_dir, neg_cache_key, ttl_seconds=negative_ttl_seconds)
            if neg is not None:
                return PriceSeries(ticker=normalized, df=pd.DataFrame())

        text = None
        if self._cache_ttl_seconds > 0:
            text = load_cached_text(self._cache_dir, cache_key, ttl_seconds=self._cache_ttl_seconds)
        if text is None:
            resp = self._session.get(url, timeout=self._timeout_s)
            resp.raise_for_status()
            text = resp.text

        df = pd.DataFrame()
        is_negative = False
        try:
            df = pd.read_csv(io.StringIO(text))
            if df.empty:
                is_negative = True
        except Exception:
            is_negative = True

        if is_negative:
            if self._cache_ttl_seconds > 0:
                save_cached_text(self._cache_dir, neg_cache_key, "1")
            return PriceSeries(ticker=normalized, df=pd.DataFrame())

        if self._cache_ttl_seconds > 0 and text is not None:
            save_cached_text(self._cache_dir, cache_key, text)

        df.columns = [c.strip().lower() for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=False)
            df = df.set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)


class YFinanceProvider(PriceProvider):
    def __init__(self, *, timeout_s: float = 30.0):
        self._timeout_s = timeout_s

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        symbol = normalized.split(".")[0]
        try:
            yf = importlib.import_module("yfinance")
        except Exception as e:
            raise ImportError("yfinance provider requires optional dependency: install stonks-cli[yfinance]") from e

        # yfinance returns a DataFrame indexed by date with OHLCV columns.
        df = yf.download(symbol, period="max", interval="1d", progress=False)
        if df is None or getattr(df, "empty", True):
            return PriceSeries(ticker=normalized, df=pd.DataFrame())

        df = df.copy()
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        try:
            df.index = pd.to_datetime(df.index)
        except Exception:
            pass
        keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
        if keep:
            df = df[keep]
        return PriceSeries(ticker=normalized, df=df)


class CsvProvider(PriceProvider):
    def __init__(self, csv_path: str):
        self._path = csv_path

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        df = pd.read_csv(self._path)
        df.columns = [c.strip().lower() for c in df.columns]
        if "ticker" in df.columns:
            want = normalized
            want_base = normalized.split(".")[0]
            tickers = df["ticker"].astype(str).str.strip().str.upper()
            df = df[(tickers == want) | (tickers == want_base)]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], utc=False)
            df = df.set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)
