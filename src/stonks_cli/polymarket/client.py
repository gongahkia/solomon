from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.polymarket.models import BookLevel, OrderBook, MarketToken, PolymarketMarket

_GAMMA_URL = "https://gamma-api.polymarket.com/markets"
_CLOB_BOOK_URL = "https://clob.polymarket.com/book"
_CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip().lower()
        if v in {"true", "1", "yes"}:
            return True
        if v in {"false", "0", "no"}:
            return False
    return None


def _pick(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _parse_tokens(raw: dict[str, Any]) -> list[MarketToken]:
    tokens_payload = _parse_jsonish(_pick(raw, "tokens"))
    if isinstance(tokens_payload, list) and tokens_payload:
        out: list[MarketToken] = []
        for token in tokens_payload:
            if not isinstance(token, dict):
                continue
            token_id = str(_pick(token, "token_id", "tokenId", "id", "asset_id", "assetId") or "").strip()
            if not token_id:
                continue
            out.append(
                MarketToken(
                    token_id=token_id,
                    outcome=str(_pick(token, "outcome", "name")) if _pick(token, "outcome", "name") else None,
                    price=_as_float(_pick(token, "price", "last_price", "lastPrice")),
                )
            )
        if out:
            return out

    token_ids = _parse_jsonish(_pick(raw, "clobTokenIds", "tokenIds"))
    outcomes = _parse_jsonish(_pick(raw, "outcomes"))
    prices = _parse_jsonish(_pick(raw, "outcomePrices"))

    if isinstance(token_ids, list):
        out = []
        for idx, token_id in enumerate(token_ids):
            outcome = None
            if isinstance(outcomes, list) and idx < len(outcomes):
                outcome = str(outcomes[idx])
            price = None
            if isinstance(prices, list) and idx < len(prices):
                price = _as_float(prices[idx])
            out.append(MarketToken(token_id=str(token_id), outcome=outcome, price=price))
        return out

    return []


def _best_level(levels: list[BookLevel], *, side: str) -> float | None:
    if not levels:
        return None
    prices = [lvl.price for lvl in levels]
    return max(prices) if side == "bid" else min(prices)


class PolymarketClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout_s: float = 15.0,
    ):
        self._session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=3,
                connect=3,
                read=3,
                status=3,
                backoff_factor=0.3,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
        self._timeout_s = timeout_s

    def list_markets(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        active: bool | None = True,
        closed: bool | None = False,
        order: str | None = "volume",
    ) -> list[PolymarketMarket]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if order:
            params["order"] = order
        resp = self._session.get(_GAMMA_URL, params=params, timeout=self._timeout_s)
        resp.raise_for_status()
        payload = json.loads(resp.text)
        if not isinstance(payload, list):
            return []
        return [self._parse_market(item) for item in payload if isinstance(item, dict)]

    def get_market(self, slug_or_id: str) -> PolymarketMarket:
        ref = (slug_or_id or "").strip()
        if not ref:
            raise ValueError("market slug or id must be non-empty")
        params = {"slug": ref} if not ref.isdigit() else {"id": ref}
        resp = self._session.get(_GAMMA_URL, params=params, timeout=self._timeout_s)
        resp.raise_for_status()
        payload = json.loads(resp.text)
        if isinstance(payload, list):
            if not payload:
                raise ValueError(f"market not found: {ref}")
            item = payload[0]
        elif isinstance(payload, dict):
            item = payload
        else:
            raise ValueError(f"unexpected market payload for: {ref}")
        if not isinstance(item, dict):
            raise ValueError(f"market not found: {ref}")
        return self._parse_market(item)

    def get_book(self, token_id: str) -> OrderBook:
        token = (token_id or "").strip()
        if not token:
            raise ValueError("token_id must be non-empty")
        resp = self._session.get(_CLOB_BOOK_URL, params={"token_id": token}, timeout=self._timeout_s)
        resp.raise_for_status()
        payload = json.loads(resp.text)
        if not isinstance(payload, dict):
            raise ValueError(f"unexpected order book payload for token {token}")
        bids = self._parse_levels(payload.get("bids"))
        asks = self._parse_levels(payload.get("asks"))
        best_bid = _best_level(bids, side="bid")
        best_ask = _best_level(asks, side="ask")
        midpoint = None
        if best_bid is not None and best_ask is not None:
            midpoint = round((best_bid + best_ask) / 2.0, 6)
        elif best_bid is not None:
            midpoint = best_bid
        elif best_ask is not None:
            midpoint = best_ask
        return OrderBook(
            token_id=token,
            bids=bids,
            asks=asks,
            midpoint=midpoint,
            best_bid=best_bid,
            best_ask=best_ask,
            raw=payload,
        )

    def get_midpoint(self, token_id: str) -> float | None:
        token = (token_id or "").strip()
        if not token:
            raise ValueError("token_id must be non-empty")
        try:
            resp = self._session.get(_CLOB_MIDPOINT_URL, params={"token_id": token}, timeout=self._timeout_s)
            resp.raise_for_status()
            payload = json.loads(resp.text)
        except Exception as e:
            log_suppressed_exception(context="polymarket.client.get_midpoint", error=e, token_id=token)
            return None

        if isinstance(payload, dict):
            return _as_float(_pick(payload, "midpoint", "value"))
        return _as_float(payload)

    def _parse_market(self, raw: dict[str, Any]) -> PolymarketMarket:
        end_date = _pick(raw, "endDate", "end_date_iso", "endDateIso", "closedTime")
        return PolymarketMarket(
            market_id=str(_pick(raw, "id", "market_id", "marketId") or ""),
            question=str(_pick(raw, "question", "title") or ""),
            slug=str(_pick(raw, "slug", "market_slug")) if _pick(raw, "slug", "market_slug") else None,
            condition_id=str(_pick(raw, "condition_id", "conditionId")) if _pick(raw, "condition_id", "conditionId") else None,
            active=_as_bool(_pick(raw, "active")),
            closed=_as_bool(_pick(raw, "closed")),
            liquidity_usd=_as_float(_pick(raw, "liquidityNum", "liquidity", "liquidity_usd")),
            volume_usd=_as_float(_pick(raw, "volumeNum", "volume", "volume_usd")),
            end_date_iso=str(end_date) if end_date else None,
            tokens=_parse_tokens(raw),
            raw=raw,
        )

    def _parse_levels(self, raw_levels: Any) -> list[BookLevel]:
        levels = _parse_jsonish(raw_levels)
        if not isinstance(levels, list):
            return []
        out: list[BookLevel] = []
        for item in levels:
            if isinstance(item, dict):
                price = _as_float(_pick(item, "price"))
                size = _as_float(_pick(item, "size", "amount"))
            elif isinstance(item, list) and len(item) >= 2:
                price = _as_float(item[0])
                size = _as_float(item[1])
            else:
                continue
            if price is None or size is None:
                continue
            out.append(BookLevel(price=price, size=size))
        return out


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
