from __future__ import annotations

import json
import os
import time

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text
from stonks_cli.data.providers import PriceProvider, PriceSeries, normalize_ticker

_BASE = "https://finnhub.io/api/v1"


class FinnhubProvider(PriceProvider):
    def __init__(self, cfg=None, cache_ttl_seconds: int = 3600):
        self._api_key = (
            getattr(getattr(cfg, "api_keys", None), "finnhub_api_key", None)
            or os.environ.get("FINNHUB_API_KEY")
        )
        if not self._api_key:
            raise ValueError("finnhub api key required via cfg.api_keys.finnhub_api_key or FINNHUB_API_KEY env")
        self._session = requests.Session()
        retry = Retry(
            total=4, connect=4, read=4, status=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)
        self._cache_dir = default_cache_dir()
        self._cache_ttl = cache_ttl_seconds
        self._timeout_s = 20.0

    def _headers(self) -> dict[str, str]:
        return {"X-Finnhub-Token": self._api_key}

    def _check_rate_limit(self, resp: requests.Response) -> None:
        remaining = resp.headers.get("X-Ratelimit-Remaining")
        if remaining is not None and int(remaining) == 0:
            raise RuntimeError("finnhub rate limit exhausted")

    def _get(self, url: str) -> requests.Response:
        resp = self._session.get(url, headers=self._headers(), timeout=self._timeout_s)
        self._check_rate_limit(resp)
        resp.raise_for_status()
        return resp

    def fetch_daily(self, ticker: str) -> PriceSeries:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0] # strip exchange suffix for Finnhub
        now = int(time.time())
        unix_from = now - 365 * 24 * 3600 # 1 year back
        unix_to = now
        cache_key = f"finnhub:daily:{base_ticker}"
        neg_cache_key = f"{cache_key}:neg"
        if self._cache_ttl > 0:
            neg = load_cached_text(self._cache_dir, neg_cache_key, ttl_seconds=300)
            if neg is not None:
                return PriceSeries(ticker=normalized, df=pd.DataFrame())
        text = None
        if self._cache_ttl > 0:
            text = load_cached_text(self._cache_dir, cache_key, ttl_seconds=self._cache_ttl)
        if text is None:
            url = f"{_BASE}/stock/candle?symbol={base_ticker}&resolution=D&from={unix_from}&to={unix_to}"
            resp = self._get(url)
            text = resp.text
        data = {}
        is_negative = False
        try:
            data = json.loads(text)
            if data.get("s") == "no_data" or "t" not in data:
                is_negative = True
        except Exception:
            is_negative = True
        if is_negative:
            if self._cache_ttl > 0:
                save_cached_text(self._cache_dir, neg_cache_key, "1")
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        if self._cache_ttl > 0 and text is not None:
            save_cached_text(self._cache_dir, cache_key, text)
        df = pd.DataFrame({
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"],
        }, index=pd.to_datetime(data["t"], unit="s", utc=False))
        df.index.name = "date"
        df = df.sort_index()
        return PriceSeries(ticker=normalized, df=df)

    def fetch_quote(self, ticker: str) -> dict:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0]
        resp = self._get(f"{_BASE}/quote?symbol={base_ticker}")
        return resp.json()

    def fetch_company_profile(self, ticker: str) -> dict:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0]
        resp = self._get(f"{_BASE}/stock/profile2?symbol={base_ticker}")
        return resp.json()

    def fetch_company_news(self, ticker: str, from_date: str, to_date: str) -> list[dict]:
        normalized = normalize_ticker(ticker)
        base_ticker = normalized.split(".")[0]
        resp = self._get(f"{_BASE}/company-news?symbol={base_ticker}&from={from_date}&to={to_date}")
        return resp.json()
