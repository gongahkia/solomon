from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarketToken:
    token_id: str
    outcome: str | None = None
    price: float | None = None


@dataclass(frozen=True)
class PolymarketMarket:
    market_id: str
    question: str
    slug: str | None
    condition_id: str | None
    active: bool | None
    closed: bool | None
    liquidity_usd: float | None
    volume_usd: float | None
    end_date_iso: str | None
    tokens: list[MarketToken] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    token_id: str
    bids: list[BookLevel]
    asks: list[BookLevel]
    midpoint: float | None
    best_bid: float | None
    best_ask: float | None
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketScan:
    market_id: str
    slug: str | None
    question: str
    token_id: str | None
    outcome: str | None
    midpoint: float | None
    bids_depth_usd: float
    asks_depth_usd: float
    liquidity_usd: float | None
    volume_usd: float | None
    hours_to_resolution: float | None
    complement_deviation_bps: float | None
    score: float
    status: str
    reasons: list[str] = field(default_factory=list)
    target_wallet_count: int = 0
    target_trade_count: int = 0
    target_net_volume: float = 0.0


@dataclass(frozen=True)
class RuntimeStatus:
    mode: str
    state: str
    paper: bool
    last_scan_at: str | None
    last_scan_count: int
    last_pass_count: int
    open_positions: int = 0
    last_actions: list[str] = field(default_factory=list)
    last_error: str | None = None


@dataclass(frozen=True)
class PaperPosition:
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    shares: float
    avg_price: float
    opened_at: str
    target_price: float | None = None
    stop_price: float | None = None
    thesis: str | None = None


@dataclass(frozen=True)
class PaperTrade:
    ts: str
    action: str
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    shares: float
    price: float
    notional: float
    realized_pnl: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class PaperAccount:
    cash: float
    realized_pnl: float
    positions: list[PaperPosition]
    trades: list[PaperTrade]


@dataclass(frozen=True)
class TradeProposal:
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    side: str
    price: float
    shares: float
    notional: float
    score: float
    target_price: float | None = None
    stop_price: float | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ProposalDecision:
    accepted: bool
    reasons: list[str]
    proposal: TradeProposal | None = None


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str | None = None


@dataclass(frozen=True)
class LiveMarketSnapshot:
    token_id: str
    best_bid: float | None = None
    best_ask: float | None = None
    midpoint: float | None = None
    last_trade_price: float | None = None
    tick_size: float = 0.01
    min_order_size: float | None = None
    bids: list[BookLevel] = field(default_factory=list)
    asks: list[BookLevel] = field(default_factory=list)
    resolved: bool = False
    winning_token_id: str | None = None
    winning_outcome: str | None = None
    last_event_type: str | None = None
    last_event_at: str | None = None


@dataclass(frozen=True)
class LiveOrderRequest:
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    side: str
    price: float
    shares: float
    post_only: bool
    tick_size: float
    reason: str | None = None


@dataclass(frozen=True)
class LiveOrderRecord:
    order_id: str
    token_id: str
    market_id: str
    slug: str | None
    outcome: str | None
    side: str
    price: float
    shares: float
    status: str
    created_at: str
    updated_at: str
    remaining_shares: float
    filled_shares: float = 0.0
    cancel_reason: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LiveOrderAction:
    action: str
    order_id: str
    token_id: str
    reason: str | None = None
