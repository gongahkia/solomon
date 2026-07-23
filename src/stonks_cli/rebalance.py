from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from enum import StrEnum

from stonks_cli.config import DecisionPriority, RebalancePolicy, StrategySettings


class AllocationBucket(StrEnum):
    INDIVIDUAL_EQUITIES = "individual_equities"
    REITS = "reits"
    BROAD_INDEX_ETFS = "broad_index_etfs"


class RebalancePlanStatus(StrEnum):
    OBSERVATION_ONLY = "observation_only"
    NO_MATERIAL_DRIFT = "no_material_drift"
    HIGHER_PRIORITY_POLICY_ACTIVE = "higher_priority_policy_active"
    GATED = "gated"
    ADVISORY_PLAN = "advisory_plan"


class RebalanceAction(StrEnum):
    BUY = "buy"
    SELL = "sell"


_BUCKETS = tuple(AllocationBucket)


@dataclass(frozen=True)
class RebalanceHolding:
    identifier: str
    bucket: AllocationBucket
    quantity: Decimal
    unit_price: Decimal
    lot_size: Decimal = Decimal("1")
    sell_fee: Decimal = Decimal("0")
    fresh: bool = True
    eligible: bool = True

    def __post_init__(self) -> None:
        identifier = self.identifier.strip().upper() if isinstance(self.identifier, str) else ""
        if not identifier or not isinstance(self.bucket, AllocationBucket):
            raise ValueError("rebalance holding identity is invalid")
        quantity = _positive_decimal(self.quantity, "rebalance holding quantity")
        unit_price = _positive_decimal(self.unit_price, "rebalance holding price")
        lot_size = _positive_decimal(self.lot_size, "rebalance holding lot size")
        sell_fee = _nonnegative_decimal(self.sell_fee, "rebalance holding fee")
        if not isinstance(self.fresh, bool) or not isinstance(self.eligible, bool):
            raise ValueError("rebalance holding freshness and eligibility must be boolean")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "unit_price", unit_price)
        object.__setattr__(self, "lot_size", lot_size)
        object.__setattr__(self, "sell_fee", sell_fee)

    @property
    def value(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass(frozen=True)
class RebalanceCandidate:
    identifier: str
    bucket: AllocationBucket
    unit_price: Decimal
    lot_size: Decimal = Decimal("1")
    buy_fee: Decimal = Decimal("0")
    fresh: bool = True
    eligible: bool = True

    def __post_init__(self) -> None:
        identifier = self.identifier.strip().upper() if isinstance(self.identifier, str) else ""
        if not identifier or not isinstance(self.bucket, AllocationBucket):
            raise ValueError("rebalance candidate identity is invalid")
        unit_price = _positive_decimal(self.unit_price, "rebalance candidate price")
        lot_size = _positive_decimal(self.lot_size, "rebalance candidate lot size")
        buy_fee = _nonnegative_decimal(self.buy_fee, "rebalance candidate fee")
        if not isinstance(self.fresh, bool) or not isinstance(self.eligible, bool):
            raise ValueError("rebalance candidate freshness and eligibility must be boolean")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "unit_price", unit_price)
        object.__setattr__(self, "lot_size", lot_size)
        object.__setattr__(self, "buy_fee", buy_fee)


@dataclass(frozen=True)
class RebalanceRequest:
    nav: Decimal
    settled_cash: Decimal
    holdings: tuple[RebalanceHolding, ...]
    candidates: tuple[RebalanceCandidate, ...]
    settings: StrategySettings
    reconciled: bool
    higher_priority_active: tuple[DecisionPriority, ...] = ()
    risk_constraints_satisfied: bool = True

    def __post_init__(self) -> None:
        nav = _positive_decimal(self.nav, "rebalance NAV")
        settled_cash = _nonnegative_decimal(self.settled_cash, "rebalance settled cash")
        if not isinstance(self.holdings, tuple) or not all(
            isinstance(item, RebalanceHolding) for item in self.holdings
        ):
            raise ValueError("rebalance holdings are invalid")
        if not isinstance(self.candidates, tuple) or not all(
            isinstance(item, RebalanceCandidate) for item in self.candidates
        ):
            raise ValueError("rebalance candidates are invalid")
        if len(set(item.identifier for item in self.holdings)) != len(self.holdings):
            raise ValueError("rebalance holdings must be unique")
        if len(set(item.identifier for item in self.candidates)) != len(self.candidates):
            raise ValueError("rebalance candidates must be unique")
        if (
            not isinstance(self.settings, StrategySettings)
            or not isinstance(self.reconciled, bool)
            or not isinstance(self.risk_constraints_satisfied, bool)
        ):
            raise ValueError("rebalance settings and reconciliation state are required")
        if not isinstance(self.higher_priority_active, tuple) or not all(
            isinstance(item, DecisionPriority) for item in self.higher_priority_active
        ):
            raise ValueError("rebalance active priorities are invalid")
        if len(set(self.higher_priority_active)) != len(self.higher_priority_active):
            raise ValueError("rebalance active priorities must be unique")
        if any(item not in self.settings.decision_priority for item in self.higher_priority_active):
            raise ValueError("rebalance active priority is not configured")
        positions_value = sum((item.value for item in self.holdings), Decimal("0"))
        if settled_cash + positions_value != nav:
            raise ValueError("rebalance NAV must equal settled cash plus position values")
        object.__setattr__(self, "nav", nav)
        object.__setattr__(self, "settled_cash", settled_cash)


@dataclass(frozen=True)
class RebalanceTrade:
    action: RebalanceAction
    identifier: str
    bucket: AllocationBucket
    quantity: Decimal
    unit_price: Decimal
    notional: Decimal
    fee: Decimal
    post_trade_quantity: Decimal
    rationale: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.action, RebalanceAction) or not isinstance(
            self.bucket, AllocationBucket
        ):
            raise ValueError("rebalance trade action and bucket are required")
        identifier = self.identifier.strip().upper() if isinstance(self.identifier, str) else ""
        if not identifier or not self.rationale or not all(self.rationale):
            raise ValueError("rebalance trade identity and rationale are required")
        quantity = _positive_decimal(self.quantity, "rebalance trade quantity")
        unit_price = _positive_decimal(self.unit_price, "rebalance trade price")
        notional = _positive_decimal(self.notional, "rebalance trade notional")
        fee = _nonnegative_decimal(self.fee, "rebalance trade fee")
        post_trade_quantity = _nonnegative_decimal(
            self.post_trade_quantity, "rebalance post-trade quantity"
        )
        if notional != quantity * unit_price:
            raise ValueError("rebalance trade notional does not match quantity and price")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "unit_price", unit_price)
        object.__setattr__(self, "notional", notional)
        object.__setattr__(self, "fee", fee)
        object.__setattr__(self, "post_trade_quantity", post_trade_quantity)


@dataclass(frozen=True)
class RebalancePlan:
    status: RebalancePlanStatus
    configuration_version: int
    before_allocation: dict[AllocationBucket, Decimal]
    after_allocation: dict[AllocationBucket, Decimal]
    before_deviation: dict[AllocationBucket, Decimal]
    after_deviation: dict[AllocationBucket, Decimal]
    settled_cash_before: Decimal
    settled_cash_after: Decimal
    trades: tuple[RebalanceTrade, ...]
    assumptions: tuple[str, ...]
    notes: tuple[str, ...]
    constraints: tuple[str, ...]
    policy_trace: tuple[DecisionPriority, ...]
    reconciled: bool
    data_fresh: bool
    total_fees: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.status, RebalancePlanStatus) or self.configuration_version < 1:
            raise ValueError("rebalance plan status and configuration version are required")
        if not all(
            set(values) == set(_BUCKETS)
            for values in (
                self.before_allocation,
                self.after_allocation,
                self.before_deviation,
                self.after_deviation,
            )
        ):
            raise ValueError("rebalance plan allocation data is incomplete")
        if not isinstance(self.trades, tuple) or not all(
            isinstance(item, RebalanceTrade) for item in self.trades
        ):
            raise ValueError("rebalance plan trades are invalid")
        if not self.assumptions or not self.notes or not self.constraints:
            raise ValueError("rebalance plan assumptions, notes, and constraints are required")
        if not isinstance(self.policy_trace, tuple) or not all(
            isinstance(item, DecisionPriority) for item in self.policy_trace
        ):
            raise ValueError("rebalance plan policy trace is invalid")
        if not isinstance(self.reconciled, bool) or not isinstance(self.data_fresh, bool):
            raise ValueError("rebalance plan data status is invalid")
        object.__setattr__(
            self, "settled_cash_before", _nonnegative_decimal(self.settled_cash_before, "cash")
        )
        object.__setattr__(
            self, "settled_cash_after", _nonnegative_decimal(self.settled_cash_after, "cash")
        )
        object.__setattr__(self, "total_fees", _nonnegative_decimal(self.total_fees, "fees"))


def simulate_rebalance(request: RebalanceRequest) -> RebalancePlan:
    if not isinstance(request, RebalanceRequest):
        raise ValueError("rebalance request is required")
    before_values = _bucket_values(request.holdings)
    before_allocation = _allocation(before_values, request.nav)
    targets = _targets(request.settings)
    before_deviation = _deviation(before_allocation, targets)
    notes = _drift_notes(before_deviation, request.settings)
    constraints = [
        "cash-funded only",
        "long-only only",
        "whole configured lots only",
        "fresh eligible holdings and candidates required",
        "post-trade position limits apply",
    ]
    gates = _gates(request)
    if gates:
        constraints.extend(gates)
        return _plan(
            RebalancePlanStatus.GATED,
            request,
            before_allocation,
            before_deviation,
            before_values,
            request.settled_cash,
            (),
            (*notes, "no advisory plan: non-bypassable gate failed"),
            tuple(constraints),
        )
    if not notes:
        return _plan(
            RebalancePlanStatus.NO_MATERIAL_DRIFT,
            request,
            before_allocation,
            before_deviation,
            before_values,
            request.settled_cash,
            (),
            ("no allocation deviation reaches the configured observation threshold",),
            tuple(constraints),
        )
    active_higher = _active_higher_priorities(request)
    if active_higher:
        return _plan(
            RebalancePlanStatus.HIGHER_PRIORITY_POLICY_ACTIVE,
            request,
            before_allocation,
            before_deviation,
            before_values,
            request.settled_cash,
            (),
            (
                *notes,
                "allocation drift is retained as a note; a higher-priority active policy suppresses compensation",
            ),
            tuple(constraints),
        )
    if request.settings.rebalance_policy is RebalancePolicy.OBSERVE_AND_REVIEW:
        return _plan(
            RebalancePlanStatus.OBSERVATION_ONLY,
            request,
            before_allocation,
            before_deviation,
            before_values,
            request.settled_cash,
            (),
            (*notes, "rebalance policy is observe-and-review; no buy or sell advisory is created"),
            tuple(constraints),
        )
    trades, after_values, after_cash = _manual_advisory_trades(request, before_values, targets)
    return _plan(
        RebalancePlanStatus.ADVISORY_PLAN,
        request,
        before_allocation,
        before_deviation,
        after_values,
        after_cash,
        trades,
        (*notes, "manual review is required; this plan cannot submit or alter an order"),
        tuple(constraints),
    )


def _manual_advisory_trades(
    request: RebalanceRequest,
    values: dict[AllocationBucket, Decimal],
    targets: dict[AllocationBucket, Decimal],
) -> tuple[tuple[RebalanceTrade, ...], dict[AllocationBucket, Decimal], Decimal]:
    quantities = {item.identifier: item.quantity for item in request.holdings}
    value_by_id = {item.identifier: item.value for item in request.holdings}
    working_values = dict(values)
    cash = request.settled_cash
    trades: list[RebalanceTrade] = []
    for bucket in _BUCKETS:
        excess = working_values[bucket] - request.nav * targets[bucket]
        if excess <= 0:
            continue
        for holding in sorted(
            (item for item in request.holdings if item.bucket is bucket),
            key=lambda item: (-value_by_id[item.identifier], item.identifier),
        ):
            if excess <= 0:
                break
            quantity = _lot_quantity(
                min(excess, value_by_id[holding.identifier]), holding.unit_price, holding.lot_size
            )
            if quantity == 0:
                continue
            notional = quantity * holding.unit_price
            post_quantity = quantities[holding.identifier] - quantity
            trade = RebalanceTrade(
                RebalanceAction.SELL,
                holding.identifier,
                bucket,
                quantity,
                holding.unit_price,
                notional,
                holding.sell_fee,
                post_quantity,
                ("allocation bucket exceeds its target", "sale is advisory-only"),
            )
            trades.append(trade)
            quantities[holding.identifier] = post_quantity
            value_by_id[holding.identifier] -= notional
            working_values[bucket] -= notional
            cash += notional - holding.sell_fee
            excess -= notional
    reserve = request.nav * Decimal(request.settings.minimum_cash_reserve)
    candidate_by_bucket: dict[AllocationBucket, list[RebalanceCandidate]] = defaultdict(list)
    for candidate in request.candidates:
        candidate_by_bucket[candidate.bucket].append(candidate)
    for bucket in _BUCKETS:
        shortfall = request.nav * targets[bucket] - working_values[bucket]
        if shortfall <= 0:
            continue
        for candidate in sorted(candidate_by_bucket[bucket], key=lambda item: item.identifier):
            if shortfall <= 0 or cash <= reserve + candidate.buy_fee:
                break
            existing_value = value_by_id.get(candidate.identifier, Decimal("0"))
            limit = _position_limit(candidate.bucket, request.settings) * request.nav
            capacity = max(limit - existing_value, Decimal("0"))
            spendable = cash - reserve - candidate.buy_fee
            desired = min(shortfall, capacity, spendable)
            quantity = _lot_quantity(desired, candidate.unit_price, candidate.lot_size)
            if quantity == 0:
                continue
            notional = quantity * candidate.unit_price
            if notional + candidate.buy_fee > cash - reserve:
                continue
            post_quantity = quantities.get(candidate.identifier, Decimal("0")) + quantity
            trade = RebalanceTrade(
                RebalanceAction.BUY,
                candidate.identifier,
                bucket,
                quantity,
                candidate.unit_price,
                notional,
                candidate.buy_fee,
                post_quantity,
                (
                    "allocation bucket is below its target",
                    "position limit and settled cash were applied",
                ),
            )
            trades.append(trade)
            quantities[candidate.identifier] = post_quantity
            value_by_id[candidate.identifier] = existing_value + notional
            working_values[bucket] += notional
            cash -= notional + candidate.buy_fee
            shortfall -= notional
    return tuple(trades), working_values, cash


def _plan(
    status: RebalancePlanStatus,
    request: RebalanceRequest,
    before_allocation: dict[AllocationBucket, Decimal],
    before_deviation: dict[AllocationBucket, Decimal],
    after_values: dict[AllocationBucket, Decimal],
    after_cash: Decimal,
    trades: tuple[RebalanceTrade, ...],
    notes: tuple[str, ...],
    constraints: tuple[str, ...],
) -> RebalancePlan:
    after_nav = sum(after_values.values(), Decimal("0")) + after_cash
    after_allocation = _allocation(after_values, after_nav)
    targets = _targets(request.settings)
    return RebalancePlan(
        status,
        request.settings.version,
        before_allocation,
        after_allocation,
        before_deviation,
        _deviation(after_allocation, targets),
        request.settled_cash,
        after_cash,
        trades,
        (
            "all values are in one reporting currency before simulation",
            "only settled cash funds purchases",
            "prices are fixed at the supplied input snapshot",
            "trades use whole configured lots",
        ),
        notes,
        constraints,
        request.settings.decision_priority,
        request.reconciled,
        all(item.fresh for item in request.holdings)
        and all(item.fresh for item in request.candidates),
        sum((item.fee for item in trades), Decimal("0")),
    )


def _gates(request: RebalanceRequest) -> tuple[str, ...]:
    gates: list[str] = []
    if not request.reconciled:
        gates.append("reconciliation_required")
    if not all(item.fresh and item.eligible for item in request.holdings) or not all(
        item.fresh and item.eligible for item in request.candidates
    ):
        gates.append("fresh_eligible_data_required")
    if request.settled_cash < request.nav * Decimal(request.settings.minimum_cash_reserve):
        gates.append("minimum_cash_reserve_not_met")
    if not request.risk_constraints_satisfied:
        gates.append("risk_constraints_required")
    return tuple(gates)


def _active_higher_priorities(request: RebalanceRequest) -> tuple[DecisionPriority, ...]:
    priorities = request.settings.decision_priority
    allocation_index = priorities.index(DecisionPriority.ALLOCATION_MAINTENANCE)
    higher = set(priorities[:allocation_index])
    return tuple(
        item for item in priorities if item in higher and item in request.higher_priority_active
    )


def _bucket_values(holdings: tuple[RebalanceHolding, ...]) -> dict[AllocationBucket, Decimal]:
    values: dict[AllocationBucket, Decimal] = {bucket: Decimal("0") for bucket in _BUCKETS}
    for holding in holdings:
        values[holding.bucket] += holding.value
    return values


def _targets(settings: StrategySettings) -> dict[AllocationBucket, Decimal]:
    return {AllocationBucket(item.asset_class): item.weight for item in settings.allocation_targets}


def _allocation(
    values: dict[AllocationBucket, Decimal], nav: Decimal
) -> dict[AllocationBucket, Decimal]:
    return {bucket: values[bucket] / nav for bucket in _BUCKETS}


def _deviation(
    allocation: dict[AllocationBucket, Decimal], targets: dict[AllocationBucket, Decimal]
) -> dict[AllocationBucket, Decimal]:
    return {bucket: allocation[bucket] - targets[bucket] for bucket in _BUCKETS}


def _drift_notes(
    deviation: dict[AllocationBucket, Decimal], settings: StrategySettings
) -> tuple[str, ...]:
    threshold = Decimal(settings.rebalance_deviation_threshold)
    return tuple(
        f"{bucket.value} deviation is {deviation[bucket]} against threshold {threshold}"
        for bucket in _BUCKETS
        if abs(deviation[bucket]) >= threshold
    )


def _position_limit(bucket: AllocationBucket, settings: StrategySettings) -> Decimal:
    return Decimal(
        settings.broad_etf_position_limit
        if bucket is AllocationBucket.BROAD_INDEX_ETFS
        else settings.individual_position_limit
    )


def _lot_quantity(value: Decimal, unit_price: Decimal, lot_size: Decimal) -> Decimal:
    lots = (value / (unit_price * lot_size)).to_integral_value(rounding=ROUND_FLOOR)
    return lots * lot_size


def _positive_decimal(value: Decimal, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except Exception as error:
        raise ValueError(f"{field} must be decimal") from error
    if not result.is_finite() or result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _nonnegative_decimal(value: Decimal, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except Exception as error:
        raise ValueError(f"{field} must be decimal") from error
    if not result.is_finite() or result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result
