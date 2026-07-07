from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class CarryRiskLimits:
    max_delta_abs: float = 0.000001
    min_margin_buffer: float = 0.20
    min_liquidation_distance: float = 0.15
    max_data_age_seconds: float = 30.0
    max_notional_usd: float = 200.0
    daily_drawdown_limit_pct: float = 0.005
    weekly_drawdown_limit_pct: float = 0.015
    global_drawdown_limit_pct: float = 0.03


@dataclass(frozen=True)
class CarryRiskState:
    asset: str
    notional_usd: float
    net_delta: float
    spot_qty: float
    perp_qty: float
    margin_buffer: float
    liquidation_distance: float
    websocket_age_seconds: float
    rest_age_seconds: float
    daily_drawdown_pct: float = 0.0
    weekly_drawdown_pct: float = 0.0
    global_drawdown_pct: float = 0.0
    hedge_present: bool = True
    configured_live_cap_usd: float = 0.0
    strategy_requested_live_cap_usd: float = 0.0


@dataclass(frozen=True)
class CarryRiskBreach:
    name: str
    inputs: dict[str, Any]


@dataclass(frozen=True)
class CarryRiskAssessment:
    ok: bool
    breaches: list[CarryRiskBreach]

    @property
    def risk_checks(self) -> list[str]:
        return [breach.name for breach in self.breaches]

    def to_dict(self) -> dict[str, Any]:
        return {
            "breaches": [asdict(breach) for breach in self.breaches],
            "ok": self.ok,
            "risk_checks": self.risk_checks,
        }


def evaluate_carry_risk(state: CarryRiskState, limits: CarryRiskLimits | None = None) -> CarryRiskAssessment:
    limits = limits or CarryRiskLimits()
    breaches: list[CarryRiskBreach] = []
    if abs(state.net_delta) > limits.max_delta_abs:
        breaches.append(
            _breach("delta_drift", net_delta=state.net_delta, max_delta_abs=limits.max_delta_abs)
        )
    if not state.hedge_present or state.spot_qty <= 0 or state.perp_qty >= 0:
        breaches.append(
            _breach("missing_hedge", hedge_present=state.hedge_present, spot_qty=state.spot_qty, perp_qty=state.perp_qty)
        )
    if state.margin_buffer < limits.min_margin_buffer:
        breaches.append(
            _breach("margin_buffer_floor", margin_buffer=state.margin_buffer, min_margin_buffer=limits.min_margin_buffer)
        )
    if state.liquidation_distance < limits.min_liquidation_distance:
        breaches.append(
            _breach(
                "liquidation_distance_floor",
                liquidation_distance=state.liquidation_distance,
                min_liquidation_distance=limits.min_liquidation_distance,
            )
        )
    if state.websocket_age_seconds > limits.max_data_age_seconds:
        breaches.append(
            _breach("stale_websocket_data", websocket_age_seconds=state.websocket_age_seconds, max_data_age_seconds=limits.max_data_age_seconds)
        )
    if state.rest_age_seconds > limits.max_data_age_seconds:
        breaches.append(
            _breach("stale_rest_data", rest_age_seconds=state.rest_age_seconds, max_data_age_seconds=limits.max_data_age_seconds)
        )
    if state.notional_usd > limits.max_notional_usd:
        breaches.append(_breach("max_notional", notional_usd=state.notional_usd, max_notional_usd=limits.max_notional_usd))
    if state.daily_drawdown_pct > limits.daily_drawdown_limit_pct:
        breaches.append(
            _breach("daily_drawdown", daily_drawdown_pct=state.daily_drawdown_pct, limit=limits.daily_drawdown_limit_pct)
        )
    if state.weekly_drawdown_pct > limits.weekly_drawdown_limit_pct:
        breaches.append(
            _breach("weekly_drawdown", weekly_drawdown_pct=state.weekly_drawdown_pct, limit=limits.weekly_drawdown_limit_pct)
        )
    if state.global_drawdown_pct > limits.global_drawdown_limit_pct:
        breaches.append(
            _breach("global_drawdown", global_drawdown_pct=state.global_drawdown_pct, limit=limits.global_drawdown_limit_pct)
        )
    if state.strategy_requested_live_cap_usd > state.configured_live_cap_usd:
        breaches.append(
            _breach(
                "no_auto_raise_live_cap",
                strategy_requested_live_cap_usd=state.strategy_requested_live_cap_usd,
                configured_live_cap_usd=state.configured_live_cap_usd,
            )
        )
    return CarryRiskAssessment(ok=not breaches, breaches=breaches)


def _breach(name: str, **inputs: Any) -> CarryRiskBreach:
    return CarryRiskBreach(name=name, inputs=inputs)
