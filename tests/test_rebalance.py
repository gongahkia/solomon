from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from stonks_cli.config import DecisionPriority, RebalancePolicy, StrategySettings
from stonks_cli.rebalance import (
    AllocationBucket,
    RebalanceAction,
    RebalanceCandidate,
    RebalanceHolding,
    RebalancePlanStatus,
    RebalanceRequest,
    simulate_rebalance,
)


def _settings(**changes: object) -> StrategySettings:
    return replace(StrategySettings(), **changes)


def _request(
    *,
    settings: StrategySettings,
    holdings: tuple[RebalanceHolding, ...] = (),
    candidates: tuple[RebalanceCandidate, ...] = (),
    cash: str = "500",
    nav: str = "1000",
    reconciled: bool = True,
    higher_priority_active: tuple[DecisionPriority, ...] = (),
    risk_constraints_satisfied: bool = True,
) -> RebalanceRequest:
    return RebalanceRequest(
        Decimal(nav),
        Decimal(cash),
        holdings,
        candidates,
        settings,
        reconciled,
        higher_priority_active,
        risk_constraints_satisfied,
    )


def test_rebalance_default_emits_allocation_drift_notes_without_trades() -> None:
    holding = RebalanceHolding(
        "US:AAA", AllocationBucket.INDIVIDUAL_EQUITIES, Decimal("5"), Decimal("100")
    )
    plan = simulate_rebalance(_request(settings=_settings(), holdings=(holding,)))

    assert plan.status is RebalancePlanStatus.OBSERVATION_ONLY
    assert plan.trades == ()
    assert any("reits deviation" in item for item in plan.notes)
    assert plan.configuration_version == 1


def test_rebalance_higher_priority_policy_suppresses_compensating_trades() -> None:
    settings = _settings(rebalance_policy=RebalancePolicy.MANUAL_ADVISORY)
    holding = RebalanceHolding(
        "US:AAA", AllocationBucket.INDIVIDUAL_EQUITIES, Decimal("5"), Decimal("100")
    )
    plan = simulate_rebalance(
        _request(
            settings=settings,
            holdings=(holding,),
            higher_priority_active=(DecisionPriority.STRATEGY_POLICY,),
        )
    )

    assert plan.status is RebalancePlanStatus.HIGHER_PRIORITY_POLICY_ACTIVE
    assert plan.trades == ()
    assert "strategy_policy" in [item.value for item in plan.policy_trace]


def test_rebalance_fails_closed_for_unreconciled_or_stale_inputs() -> None:
    settings = _settings(rebalance_policy=RebalancePolicy.MANUAL_ADVISORY)
    stale = RebalanceCandidate(
        "US:BBB", AllocationBucket.BROAD_INDEX_ETFS, Decimal("10"), fresh=False
    )
    plan = simulate_rebalance(
        _request(
            settings=settings,
            candidates=(stale,),
            cash="1000",
            reconciled=False,
            risk_constraints_satisfied=False,
        )
    )

    assert plan.status is RebalancePlanStatus.GATED
    assert plan.trades == ()
    assert "reconciliation_required" in plan.constraints
    assert "fresh_eligible_data_required" in plan.constraints
    assert "risk_constraints_required" in plan.constraints
    assert not plan.reconciled
    assert not plan.data_fresh


def test_manual_rebalance_respects_settled_cash_lots_and_position_limits() -> None:
    settings = _settings(rebalance_policy=RebalancePolicy.MANUAL_ADVISORY, version=3)
    holding = RebalanceHolding(
        "US:AAA", AllocationBucket.INDIVIDUAL_EQUITIES, Decimal("5"), Decimal("100")
    )
    candidates = (
        RebalanceCandidate("US:REIT", AllocationBucket.REITS, Decimal("1")),
        RebalanceCandidate("US:ETF", AllocationBucket.BROAD_INDEX_ETFS, Decimal("1")),
    )
    plan = simulate_rebalance(
        _request(settings=settings, holdings=(holding,), candidates=candidates)
    )

    assert plan.status is RebalancePlanStatus.ADVISORY_PLAN
    assert [(item.action, item.identifier, item.quantity) for item in plan.trades] == [
        (RebalanceAction.BUY, "US:REIT", Decimal("50")),
        (RebalanceAction.BUY, "US:ETF", Decimal("200")),
    ]
    assert plan.settled_cash_after == Decimal("250")
    assert plan.total_fees == Decimal("0")
    assert "cash-funded only" in plan.constraints
    assert "only settled cash funds purchases" in plan.assumptions


def test_manual_rebalance_can_sell_overweight_holdings_before_buying() -> None:
    settings = _settings(rebalance_policy=RebalancePolicy.MANUAL_ADVISORY)
    holdings = (
        RebalanceHolding(
            "US:AAA", AllocationBucket.INDIVIDUAL_EQUITIES, Decimal("10"), Decimal("50")
        ),
        RebalanceHolding("US:REIT", AllocationBucket.REITS, Decimal("5"), Decimal("100")),
    )
    candidate = RebalanceCandidate("US:ETF", AllocationBucket.BROAD_INDEX_ETFS, Decimal("1"))
    plan = simulate_rebalance(
        _request(settings=settings, holdings=holdings, candidates=(candidate,), cash="0")
    )

    assert plan.status is RebalancePlanStatus.ADVISORY_PLAN
    assert plan.trades[0].action is RebalanceAction.SELL
    assert any(item.action is RebalanceAction.BUY for item in plan.trades)
