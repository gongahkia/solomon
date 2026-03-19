from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stonks_cli.data.cache import default_cache_dir, load_cached_text, save_cached_text
from stonks_cli.data.providers import PriceProvider, PriceSeries, normalize_ticker

_PREFIX = "POLYMARKET:"
_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
_CLOB_URL = "https://clob.polymarket.com/prices-history"


def _strip_prefix(ticker: str) -> str:
    t = ticker.strip()
    upper = t.upper()
    if upper.startswith(_PREFIX):
        return t[len(_PREFIX) :]
    return t


def _normalize_polymarket_ticker(raw: str) -> str:
    t = raw.strip()
    if not t:
        raise ValueError("Ticker cannot be empty")
    if t.upper().startswith(_PREFIX):
        return t.upper()  # keep POLYMARKET:<SLUG> form, no .US suffix
    return normalize_ticker(t)


class PolymarketProvider(PriceProvider):
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
        normalized = _normalize_polymarket_ticker(ticker)
        slug = _strip_prefix(ticker).lower()
        cache_key = f"polymarket:daily:{slug}"
        neg_cache_key = f"{cache_key}:neg"
        negative_ttl = 300
        if self._cache_ttl_seconds > 0:
            neg = load_cached_text(self._cache_dir, neg_cache_key, ttl_seconds=negative_ttl)
            if neg is not None:
                return PriceSeries(ticker=normalized, df=pd.DataFrame())
        # resolve condition_id via gamma-api
        condition_id = self._resolve_condition_id(slug, cache_key)
        if condition_id is None:
            if self._cache_ttl_seconds > 0:
                save_cached_text(self._cache_dir, neg_cache_key, "1")
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        # fetch price history from clob
        history_key = f"polymarket:history:{condition_id}"
        history_text = None
        if self._cache_ttl_seconds > 0:
            history_text = load_cached_text(self._cache_dir, history_key, ttl_seconds=self._cache_ttl_seconds)
        if history_text is None:
            resp = self._session.get(
                _CLOB_URL,
                params={"market": condition_id, "interval": "1d", "fidelity": "100"},
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
            history_text = resp.text
            if self._cache_ttl_seconds > 0 and history_text:
                save_cached_text(self._cache_dir, history_key, history_text)
        try:
            data = json.loads(history_text)
        except Exception:
            if self._cache_ttl_seconds > 0:
                save_cached_text(self._cache_dir, neg_cache_key, "1")
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        history = data.get("history", data) if isinstance(data, dict) else data
        if not history:
            return PriceSeries(ticker=normalized, df=pd.DataFrame())
        rows = [{"date": pd.to_datetime(h["t"], unit="s", utc=False), "close": float(h["p"])} for h in history]
        df = pd.DataFrame(rows).set_index("date").sort_index()
        return PriceSeries(ticker=normalized, df=df)

    def _resolve_condition_id(self, slug: str, cache_key: str) -> str | None:
        meta_key = f"{cache_key}:meta"
        meta_text = None
        if self._cache_ttl_seconds > 0:
            meta_text = load_cached_text(self._cache_dir, meta_key, ttl_seconds=self._cache_ttl_seconds)
        if meta_text is None:
            resp = self._session.get(
                _GAMMA_URL,
                params={"slug": slug},
                timeout=self._timeout_s,
            )
            resp.raise_for_status()
            meta_text = resp.text
            if self._cache_ttl_seconds > 0 and meta_text:
                save_cached_text(self._cache_dir, meta_key, meta_text)
        try:
            markets = json.loads(meta_text)
        except Exception:
            return None
        if isinstance(markets, list) and len(markets) > 0:
            return markets[0].get("condition_id")
        if isinstance(markets, dict):
            return markets.get("condition_id")
        return None

    def fetch_markets(self, query: str) -> list[dict]:
        """Search markets on Polymarket."""
        resp = self._session.get(
            _GAMMA_URL,
            params={"_q": query},
            timeout=self._timeout_s,
        )
        resp.raise_for_status()
        try:
            return json.loads(resp.text)
        except Exception:
            return []

    def fetch_orderbook(self, condition_id: str) -> dict:
        """Fetch orderbook for a given condition_id."""
        resp = self._session.get(
            "https://clob.polymarket.com/book",
            params={"token_id": condition_id},
            timeout=self._timeout_s,
        )
        resp.raise_for_status()
        try:
            return json.loads(resp.text)
        except Exception:
            return {}
