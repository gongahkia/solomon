from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from stonks_cli.carry.carry_audit import CarryReconciliationReport
from stonks_cli.config import AppConfig
from stonks_cli.legal_policy import evaluate_legal_policy
from stonks_cli.research.hyperliquid import HyperliquidCarryInput, HyperliquidOrderClient, HyperliquidOrderIntent
from stonks_cli.research.models import CarryDecision, ExecutionMode, Venue

TRUTHY_CARRY_ARM_VALUES = frozenset({"1", "true", "yes", "armed"})


@dataclass(frozen=True)
class CarryLivePreflightEvidence:
    paper_gate_passed: bool = False
    legal_review_recorded: bool = False
    venue_health_ok: bool = False
    manual_cap_confirmed: bool = False
    requested_notional_usd: float = 0.0
    cap_usd: float = 0.0
    secrets_path: str | None = None


@dataclass(frozen=True)
class CarryLivePreflight:
    ok: bool
    blockers: list[str]
    env_var: str
    cap_usd: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CarryLiveOrderPlan:
    venue: Venue
    asset: str
    notional_usd: float
    spot_order: HyperliquidOrderIntent
    perp_order: HyperliquidOrderIntent
    risk_checks: list[str]
    client_order_group: str

    @property
    def orders(self) -> list[HyperliquidOrderIntent]:
        return [self.spot_order, self.perp_order]

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset,
            "client_order_group": self.client_order_group,
            "notional_usd": self.notional_usd,
            "orders": [order.to_exchange_order() for order in self.orders],
            "risk_checks": list(self.risk_checks),
            "venue": str(self.venue),
        }


@dataclass(frozen=True)
class CarryLiveFillState:
    asset: str
    spot_filled_qty: float
    perp_filled_qty: float
    timed_out: bool


@dataclass(frozen=True)
class CarryLiveRecoveryPlan:
    action: str
    orders: list[HyperliquidOrderIntent] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"action": self.action, "blockers": list(self.blockers), "orders": [order.to_exchange_order() for order in self.orders]}


@dataclass(frozen=True)
class CarryLiveReconciliationGate:
    ok: bool
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_carry_live_preflight(
    *,
    cfg: AppConfig,
    evidence: CarryLivePreflightEvidence,
    env: dict[str, str] | None = None,
) -> CarryLivePreflight:
    use_env = os.environ if env is None else env
    blockers: list[str] = []
    env_value = use_env.get(cfg.carry.live_armed_env, "").strip().lower()
    cap = cfg.carry.max_total_live_usd
    secrets_path = Path(evidence.secrets_path or cfg.carry.live_secrets_path).expanduser()
    if not cfg.carry.live_armed:
        blockers.append("carry_live_config_not_armed")
    if env_value not in TRUTHY_CARRY_ARM_VALUES:
        blockers.append(f"carry_live_env_not_armed:{cfg.carry.live_armed_env}")
    if not evidence.paper_gate_passed:
        blockers.append("paper_gate_not_passed")
    if not evidence.legal_review_recorded:
        blockers.append("legal_review_not_recorded")
    if not evidence.venue_health_ok:
        blockers.append("venue_health_not_ok")
    if not evidence.manual_cap_confirmed:
        blockers.append("manual_cap_not_confirmed")
    if not secrets_path.exists():
        blockers.append(f"secrets_path_missing:{secrets_path}")
    if cap <= 0:
        blockers.append("live_cap_not_configured")
    if evidence.cap_usd and evidence.cap_usd != cap:
        blockers.append(f"manual_cap_mismatch:{evidence.cap_usd}!={cap}")
    if cap < cfg.carry.tiny_live_min_usd or cap > cfg.carry.tiny_live_max_usd:
        blockers.append(f"cap_outside_tiny_live_bounds:{cap}")
    if evidence.requested_notional_usd <= 0:
        blockers.append("requested_notional_not_positive")
    if evidence.requested_notional_usd > cap:
        blockers.append(f"requested_notional_exceeds_cap:{evidence.requested_notional_usd}>{cap}")
    legal = evaluate_legal_policy(cfg, venue_id="hyperliquid", strategy_class="carry_funding_basis")
    blockers.extend(legal.blockers)
    return CarryLivePreflight(ok=not blockers, blockers=blockers, env_var=cfg.carry.live_armed_env, cap_usd=cap)


def build_carry_live_entry_plan(
    *,
    inputs: HyperliquidCarryInput,
    notional_usd: float,
    spot_asset_index: int,
    perp_asset_index: int,
    slippage_bps: float = 3.0,
    client_order_seed: int = 1,
) -> CarryLiveOrderPlan:
    if inputs.quote.spot_mid is None or inputs.quote.perp_mid is None:
        raise ValueError("spot_mid and perp_mid are required")
    if notional_usd <= 0:
        raise ValueError("notional_usd must be positive")
    quantity = notional_usd / ((inputs.quote.spot_mid + inputs.quote.perp_mid) / 2)
    group = _cloid(client_order_seed)
    spot_order = HyperliquidOrderIntent(
        asset_index=10000 + spot_asset_index,
        coin=f"{inputs.asset}/USDC",
        is_buy=True,
        limit_px=_decimal(inputs.quote.spot_mid * (1 + slippage_bps / 10000)),
        size=_decimal(quantity),
        reduce_only=False,
        tif="Alo",
        cloid=_cloid(client_order_seed + 1),
    )
    perp_order = HyperliquidOrderIntent(
        asset_index=perp_asset_index,
        coin=inputs.asset,
        is_buy=False,
        limit_px=_decimal(inputs.quote.perp_mid * (1 - slippage_bps / 10000)),
        size=_decimal(quantity),
        reduce_only=False,
        tif="Alo",
        cloid=_cloid(client_order_seed + 2),
    )
    return CarryLiveOrderPlan(
        venue=Venue.HYPERLIQUID,
        asset=inputs.asset,
        notional_usd=notional_usd,
        spot_order=spot_order,
        perp_order=perp_order,
        risk_checks=["tiny_live", "matched_spot_perp_intents", "post_only_entry"],
        client_order_group=group,
    )


def build_carry_live_reduce_only_exit_plan(
    *,
    asset: str,
    spot_qty: float,
    perp_qty: float,
    spot_asset_index: int,
    perp_asset_index: int,
    spot_limit_px: float,
    perp_limit_px: float,
    client_order_seed: int = 100,
    venue: Venue | str = Venue.HYPERLIQUID,
) -> CarryLiveOrderPlan:
    if Venue(venue) is not Venue.HYPERLIQUID:
        raise ValueError(f"unsupported_reduce_only_exit_venue:{venue}")
    if spot_qty <= 0 or perp_qty >= 0:
        raise ValueError("exit plan requires long spot and short perp quantities")
    spot_order = HyperliquidOrderIntent(
        asset_index=10000 + spot_asset_index,
        coin=f"{asset}/USDC",
        is_buy=False,
        limit_px=_decimal(spot_limit_px),
        size=_decimal(abs(spot_qty)),
        reduce_only=False,
        tif="Ioc",
        cloid=_cloid(client_order_seed + 1),
    )
    perp_order = HyperliquidOrderIntent(
        asset_index=perp_asset_index,
        coin=asset,
        is_buy=True,
        limit_px=_decimal(perp_limit_px),
        size=_decimal(abs(perp_qty)),
        reduce_only=True,
        tif="Ioc",
        cloid=_cloid(client_order_seed + 2),
    )
    return CarryLiveOrderPlan(
        venue=Venue.HYPERLIQUID,
        asset=asset,
        notional_usd=0.0,
        spot_order=spot_order,
        perp_order=perp_order,
        risk_checks=["reduce_only_perp_exit", "ioc_exit"],
        client_order_group=_cloid(client_order_seed),
    )


def plan_carry_partial_fill_recovery(
    *,
    fill_state: CarryLiveFillState,
    spot_asset_index: int,
    perp_asset_index: int,
    spot_limit_px: float,
    perp_limit_px: float,
    max_delta_abs: float,
    client_order_seed: int = 200,
) -> CarryLiveRecoveryPlan:
    delta = fill_state.spot_filled_qty + fill_state.perp_filled_qty
    if abs(delta) <= max_delta_abs:
        return CarryLiveRecoveryPlan(action="none")
    if not fill_state.timed_out:
        return CarryLiveRecoveryPlan(action="wait", blockers=["partial_fill_timeout_not_reached"])
    if fill_state.spot_filled_qty > abs(fill_state.perp_filled_qty):
        qty = fill_state.spot_filled_qty - abs(fill_state.perp_filled_qty)
        return CarryLiveRecoveryPlan(
            action="exit_unhedged_spot",
            orders=[
                HyperliquidOrderIntent(
                    asset_index=10000 + spot_asset_index,
                    coin=f"{fill_state.asset}/USDC",
                    is_buy=False,
                    limit_px=_decimal(spot_limit_px),
                    size=_decimal(qty),
                    reduce_only=False,
                    tif="Ioc",
                    cloid=_cloid(client_order_seed),
                )
            ],
        )
    qty = abs(fill_state.perp_filled_qty) - fill_state.spot_filled_qty
    return CarryLiveRecoveryPlan(
        action="exit_unhedged_perp_reduce_only",
        orders=[
            HyperliquidOrderIntent(
                asset_index=perp_asset_index,
                coin=fill_state.asset,
                is_buy=True,
                limit_px=_decimal(perp_limit_px),
                size=_decimal(qty),
                reduce_only=True,
                tif="Ioc",
                cloid=_cloid(client_order_seed),
            )
        ],
    )


def evaluate_carry_live_reconciliation(
    *,
    report: CarryReconciliationReport,
    ledger_decisions: list[CarryDecision],
    required_decision_ids: list[str],
) -> CarryLiveReconciliationGate:
    blockers: list[str] = []
    if report.blocks_live:
        blockers.append("reconciliation_blocks_live")
    existing_ids = {decision.decision_id for decision in ledger_decisions}
    for decision_id in required_decision_ids:
        if decision_id not in existing_ids:
            blockers.append(f"missing_ledger_row:{decision_id}")
    return CarryLiveReconciliationGate(ok=not blockers, blockers=blockers)


def submit_carry_live_entry_plan(
    *,
    preflight: CarryLivePreflight,
    plan: CarryLiveOrderPlan,
    client: HyperliquidOrderClient,
    nonce: int | None = None,
    signature: Any | None = None,
) -> dict[str, Any]:
    if not preflight.ok:
        raise ValueError("; ".join(preflight.blockers))
    if len(plan.orders) != 2:
        raise ValueError("carry_live_plan_requires_two_matched_orders")
    return client.create_order(
        plan.orders,
        mode=ExecutionMode.LIVE,
        nonce=nonce,
        signature=signature,
        extra_guard_reasons=[],
        heartbeat_ok=True,
        emergency_stop_active=False,
        consensus_approved=True,
    )


def _decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 8)))


def _cloid(seed: int) -> str:
    return f"0x{seed:032x}"
