from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from stonks_cli.polymarket.client import PolymarketClient
from stonks_cli.polymarket.models import MarketScan, OrderBook, PolymarketMarket


@dataclass(frozen=True)
class StructuralScanConfig:
    min_market_liquidity_usd: float = 50000.0
    min_book_depth_usd: float = 500.0
    min_hours_to_resolution: float = 4.0
    max_hours_to_resolution: float = 168.0
    require_active: bool = True


def primary_token(market: PolymarketMarket):
    if not market.tokens:
        return None
    for token in market.tokens:
        outcome = (token.outcome or "").strip().lower()
        if outcome == "yes":
            return token
    return market.tokens[0]


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def hours_to_resolution(market: PolymarketMarket, *, now: datetime | None = None) -> float | None:
    end_dt = _parse_iso_datetime(market.end_date_iso)
    if end_dt is None:
        return None
    now_dt = now or datetime.now(UTC)
    return (end_dt - now_dt).total_seconds() / 3600.0


def book_depth_usd(levels) -> float:
    return round(sum(max(0.0, lvl.price) * max(0.0, lvl.size) for lvl in levels), 2)


def complement_deviation_bps(market: PolymarketMarket) -> float | None:
    prices = [token.price for token in market.tokens if token.price is not None]
    if len(prices) < 2:
        return None
    return round(abs(sum(prices) - 1.0) * 10000.0, 2)


def structural_scan_market(
    market: PolymarketMarket,
    book: OrderBook,
    cfg: StructuralScanConfig,
    *,
    now: datetime | None = None,
) -> MarketScan:
    token = primary_token(market)
    bids_depth = book_depth_usd(book.bids)
    asks_depth = book_depth_usd(book.asks)
    hrs = hours_to_resolution(market, now=now)
    deviation_bps = complement_deviation_bps(market)
    reasons: list[str] = []

    if cfg.require_active and market.active is False:
        reasons.append("inactive")
    if market.closed:
        reasons.append("closed")
    if market.liquidity_usd is not None and market.liquidity_usd < cfg.min_market_liquidity_usd:
        reasons.append(f"liquidity<{cfg.min_market_liquidity_usd:.0f}")
    if bids_depth < cfg.min_book_depth_usd or asks_depth < cfg.min_book_depth_usd:
        reasons.append(f"depth<{cfg.min_book_depth_usd:.0f}")
    if hrs is not None and hrs < cfg.min_hours_to_resolution:
        reasons.append(f"hours<{cfg.min_hours_to_resolution:.1f}")
    if hrs is not None and hrs > cfg.max_hours_to_resolution:
        reasons.append(f"hours>{cfg.max_hours_to_resolution:.1f}")

    depth_balance = min(bids_depth, asks_depth)
    time_score = 0.0
    if hrs is not None:
        sweet_spot = 24.0
        time_score = max(0.0, 1.0 - min(abs(hrs - sweet_spot) / sweet_spot, 1.0))

    deviation_score = (deviation_bps or 0.0) / 100.0
    score = round((depth_balance / 1000.0) + deviation_score + (time_score * 10.0), 2)
    status = "PASS" if not reasons else "FILTERED"

    return MarketScan(
        market_id=market.market_id,
        slug=market.slug,
        question=market.question,
        token_id=token.token_id if token else None,
        outcome=token.outcome if token else None,
        midpoint=book.midpoint,
        bids_depth_usd=bids_depth,
        asks_depth_usd=asks_depth,
        liquidity_usd=market.liquidity_usd,
        volume_usd=market.volume_usd,
        hours_to_resolution=round(hrs, 2) if hrs is not None else None,
        complement_deviation_bps=deviation_bps,
        score=score,
        status=status,
        reasons=reasons,
    )


def scan_markets(
    client: PolymarketClient,
    *,
    limit: int,
    cfg: StructuralScanConfig,
    include_filtered: bool = False,
) -> list[MarketScan]:
    markets = client.list_markets(limit=limit, active=cfg.require_active, closed=False, order="volume")
    scans: list[MarketScan] = []
    for market in markets:
        token = primary_token(market)
        if token is None:
            if include_filtered:
                scans.append(
                    MarketScan(
                        market_id=market.market_id,
                        slug=market.slug,
                        question=market.question,
                        token_id=None,
                        outcome=None,
                        midpoint=None,
                        bids_depth_usd=0.0,
                        asks_depth_usd=0.0,
                        liquidity_usd=market.liquidity_usd,
                        volume_usd=market.volume_usd,
                        hours_to_resolution=hours_to_resolution(market),
                        complement_deviation_bps=complement_deviation_bps(market),
                        score=0.0,
                        status="FILTERED",
                        reasons=["missing_token"],
                    )
                )
            continue
        book = client.get_book(token.token_id)
        scan = structural_scan_market(market, book, cfg)
        if include_filtered or scan.status == "PASS":
            scans.append(scan)
    scans.sort(key=lambda item: item.score, reverse=True)
    return scans


def enrich_scans_with_wallet_signals(scans: list[MarketScan], signals) -> list[MarketScan]:
    by_market_outcome = {(signal.market_id, signal.outcome.upper()): signal for signal in signals}
    enriched: list[MarketScan] = []
    for scan in scans:
        outcome = (scan.outcome or "").upper()
        signal = by_market_outcome.get((scan.market_id, outcome))
        if signal is None:
            enriched.append(scan)
            continue
        extra_score = min(signal.wallet_count * 2.0, 10.0) + min(signal.trade_count / 10.0, 5.0)
        enriched.append(
            MarketScan(
                market_id=scan.market_id,
                slug=scan.slug,
                question=scan.question,
                token_id=scan.token_id,
                outcome=scan.outcome,
                midpoint=scan.midpoint,
                bids_depth_usd=scan.bids_depth_usd,
                asks_depth_usd=scan.asks_depth_usd,
                liquidity_usd=scan.liquidity_usd,
                volume_usd=scan.volume_usd,
                hours_to_resolution=scan.hours_to_resolution,
                complement_deviation_bps=scan.complement_deviation_bps,
                score=round(scan.score + extra_score, 2),
                status=scan.status,
                reasons=list(scan.reasons),
                target_wallet_count=signal.wallet_count,
                target_trade_count=signal.trade_count,
                target_net_volume=signal.net_volume,
            )
        )
    enriched.sort(key=lambda item: item.score, reverse=True)
    return enriched
