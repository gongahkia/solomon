from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.scanner import StructuralScanConfig, scan_markets


class _Resp:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, markets_payload: list[dict], books_by_token: dict[str, dict]):
        self._markets_payload = markets_payload
        self._books_by_token = books_by_token

    def get(self, url: str, params=None, timeout: float = 15.0):
        if "gamma-api" in url:
            return _Resp(json.dumps(self._markets_payload))
        token_id = str((params or {}).get("token_id"))
        return _Resp(json.dumps(self._books_by_token[token_id]))


def _market(*, market_id: str, token_id: str, liquidity: float, hours: float, active: bool = True) -> dict:
    end = datetime.now(UTC) + timedelta(hours=hours)
    return {
        "id": market_id,
        "question": f"Question {market_id}",
        "slug": f"market-{market_id}",
        "condition_id": f"cond-{market_id}",
        "active": active,
        "closed": False,
        "liquidityNum": liquidity,
        "volumeNum": 250000,
        "endDate": end.isoformat().replace("+00:00", "Z"),
        "tokens": [
            {"token_id": token_id, "outcome": "Yes", "price": 0.55},
            {"token_id": f"{token_id}-no", "outcome": "No", "price": 0.46},
        ],
    }


def _book(*, bid_price: float, bid_size: float, ask_price: float, ask_size: float) -> dict:
    return {
        "bids": [{"price": bid_price, "size": bid_size}],
        "asks": [{"price": ask_price, "size": ask_size}],
    }


def test_scan_markets_only_returns_passes_by_default():
    session = _Session(
        markets_payload=[
            _market(market_id="1", token_id="YES1", liquidity=100000, hours=12),
            _market(market_id="2", token_id="YES2", liquidity=1000, hours=2),
        ],
        books_by_token={
            "YES1": _book(bid_price=0.54, bid_size=5000, ask_price=0.56, ask_size=5000),
            "YES2": _book(bid_price=0.40, bid_size=10, ask_price=0.60, ask_size=10),
        },
    )
    client = PolymarketClient(session=session)
    cfg = StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )

    scans = scan_markets(client, limit=10, cfg=cfg, include_filtered=False)

    assert len(scans) == 1
    assert scans[0].market_id == "1"
    assert scans[0].status == "PASS"
    assert scans[0].midpoint == 0.55


def test_scan_markets_can_include_filtered_rows():
    session = _Session(
        markets_payload=[
            _market(market_id="1", token_id="YES1", liquidity=100000, hours=12),
            _market(market_id="2", token_id="YES2", liquidity=1000, hours=2),
        ],
        books_by_token={
            "YES1": _book(bid_price=0.54, bid_size=5000, ask_price=0.56, ask_size=5000),
            "YES2": _book(bid_price=0.40, bid_size=10, ask_price=0.60, ask_size=10),
        },
    )
    client = PolymarketClient(session=session)
    cfg = StructuralScanConfig(
        min_market_liquidity_usd=50000,
        min_book_depth_usd=500,
        min_hours_to_resolution=4,
        max_hours_to_resolution=168,
        require_active=True,
    )

    scans = scan_markets(client, limit=10, cfg=cfg, include_filtered=True)

    assert len(scans) == 2
    filtered = [scan for scan in scans if scan.market_id == "2"][0]
    assert filtered.status == "FILTERED"
    assert "liquidity<50000" in filtered.reasons
    assert "depth<500" in filtered.reasons
