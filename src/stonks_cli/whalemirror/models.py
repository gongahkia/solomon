from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Venue(StrEnum):
    HYPERLIQUID = "hyperliquid"
    SOLANA = "solana"
    EVM_PERP_DEX = "evm_perp_dex"
    OKX = "okx"
    BYBIT = "bybit"
    POLYMARKET = "polymarket"
    KALSHI = "kalshi"
    SPORTSBOOK = "sportsbook"


class TradeSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
    LONG = "long"
    SHORT = "short"


class MirrorMode(StrEnum):
    PAPER = "paper"
    DRY_RUN = "dry_run"
    LIVE = "live"


SG_BLOCKED_EXECUTION_VENUES = frozenset({Venue.BYBIT, Venue.POLYMARKET, Venue.KALSHI, Venue.SPORTSBOOK})
SG_BLOCKED_STRATEGY_CLASSES = frozenset(
    {"circumvention", "prediction_market", "sports_betting", "sportsbook", "whalemirror_live_target_selection"}
)


def coerce_venue(value: Venue | str) -> Venue:
    if isinstance(value, Venue):
        return value
    try:
        return Venue(str(value).strip().lower())
    except ValueError:
        raise ValueError(f"unsupported venue: {value!r}")


def coerce_side(value: TradeSide | str) -> TradeSide:
    if isinstance(value, TradeSide):
        return value
    try:
        return TradeSide(str(value).strip().lower())
    except ValueError:
        raise ValueError(f"unsupported trade side: {value!r}")


def coerce_mode(value: MirrorMode | str) -> MirrorMode:
    if isinstance(value, MirrorMode):
        return value
    try:
        return MirrorMode(str(value).strip().lower())
    except ValueError:
        raise ValueError(f"unsupported mirror mode: {value!r}")


@dataclass(frozen=True)
class NormalizedTrade:
    venue: Venue
    trade_id: str
    wallet: str
    market: str
    asset: str
    side: TradeSide
    price: float
    size: float
    notional_usd: float
    observed_at: str
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))
        object.__setattr__(self, "side", coerce_side(self.side))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class ExecutionIntent:
    venue: Venue
    mode: MirrorMode
    source_trade_id: str
    wallet: str
    market: str
    asset: str
    side: TradeSide
    order_type: str
    price: float | None
    size: float
    notional_usd: float
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))
        object.__setattr__(self, "mode", coerce_mode(self.mode))
        object.__setattr__(self, "side", coerce_side(self.side))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class AttributionMetrics:
    wallet: str
    venue: Venue
    expectancy: float
    sharpe: float
    decay: float
    survivorship_adjusted_pnl: float
    funding_adjusted_pnl: float
    sample_size: int
    caveats: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class DecisionRecord:
    timestamp_utc: str
    mode: MirrorMode
    venue: Venue
    signal: str
    decision: str
    rationale: str
    receipt: str | None = None
    outcome: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", coerce_mode(self.mode))
        object.__setattr__(self, "venue", coerce_venue(self.venue))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class CarryQuote:
    venue: Venue
    asset: str
    spot_mid: float | None
    perp_mid: float | None
    oracle_mid: float | None
    mark_mid: float | None
    timestamp: str
    source_health: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class FundingSnapshot:
    asset: str
    venue: Venue
    hourly_rate: float
    annualized_rate: float
    next_funding_time: str | None
    premium_index: float | None
    timestamp: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class BasisSnapshot:
    asset: str
    spot_mid: float
    perp_mid: float
    basis_abs: float
    basis_pct: float
    annualized_basis: float
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class CarryOpportunity:
    asset: str
    venue: Venue
    direction: str
    net_apr: float
    gross_apr: float
    fee_bps: float
    slippage_bps: float
    buffer_bps: float
    required_fields_missing: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "venue", coerce_venue(self.venue))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class CarryPosition:
    asset: str
    spot_qty: float
    perp_qty: float
    net_delta: float
    entry_basis: float
    accrued_funding: float
    fees: float
    margin_buffer: float
    liquidation_distance: float

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


@dataclass(frozen=True)
class CarryDecision:
    decision_id: str
    mode: MirrorMode
    action: str
    reason: str
    inputs: dict[str, Any]
    risk_checks: list[str]
    expected_net_apr: float
    exit_rule: str
    timestamp: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "mode", coerce_mode(self.mode))

    def to_dict(self) -> dict[str, Any]:
        return _json_ready(asdict(self))


def _json_ready(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_ready(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    return value
