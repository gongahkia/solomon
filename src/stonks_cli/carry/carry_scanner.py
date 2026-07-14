from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.config import AppConfig
from stonks_cli.research.hyperliquid import (
    HYPERLIQUID_INFO_URL,
    HyperliquidCarryInput,
    HyperliquidOrderClient,
    blocked_carry_opportunity,
    validate_carry_input_completeness,
)
from stonks_cli.research.models import BasisSnapshot, CarryOpportunity, CarryQuote, FundingSnapshot, Venue


@dataclass(frozen=True)
class CarryCostAssumptions:
    fee_bps: float = 4.0
    slippage_bps: float = 5.0
    rebalance_bps: float = 5.0
    borrow_bps: float = 0.0
    volatility_buffer_bps: float = 25.0

    @property
    def total_cost_apr(self) -> float:
        return (
            self.fee_bps
            + self.slippage_bps
            + self.rebalance_bps
            + self.borrow_bps
            + self.volatility_buffer_bps
        ) / 10000

    def to_dict(self) -> dict[str, float]:
        payload = asdict(self)
        payload["total_cost_apr"] = self.total_cost_apr
        return payload


@dataclass(frozen=True)
class CarryScanRow:
    opportunity: CarryOpportunity
    status: str
    threshold_met: bool
    min_net_apr: float
    cost_assumptions: CarryCostAssumptions
    source_health: dict[str, str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_assumptions": self.cost_assumptions.to_dict(),
            "metadata": self.metadata,
            "min_net_apr": self.min_net_apr,
            "opportunity": self.opportunity.to_dict(),
            "source_health": self.source_health,
            "status": self.status,
            "threshold_met": self.threshold_met,
        }


def scan_hyperliquid_carry(
    *,
    cfg: AppConfig,
    client: HyperliquidOrderClient | None = None,
    inputs: list[HyperliquidCarryInput] | None = None,
    assets: tuple[str, ...] = ("BTC", "ETH"),
    assumptions: CarryCostAssumptions | None = None,
    now: datetime | None = None,
) -> list[CarryScanRow]:
    assumptions = assumptions or CarryCostAssumptions()
    source_inputs = inputs
    if source_inputs is None:
        client = client or HyperliquidOrderClient(info_url=HYPERLIQUID_INFO_URL)
        source_inputs = client.fetch_carry_inputs(assets=assets)
    return [
        calculate_carry_scan_row(
            row,
            min_net_apr=cfg.carry.min_net_apr,
            assumptions=assumptions,
            now=now,
        )
        for row in source_inputs
    ]


def calculate_carry_scan_row(
    inputs: HyperliquidCarryInput,
    *,
    min_net_apr: float,
    assumptions: CarryCostAssumptions | None = None,
    now: datetime | None = None,
) -> CarryScanRow:
    assumptions = assumptions or CarryCostAssumptions()
    validation = validate_carry_input_completeness(inputs, now=now or datetime.now(UTC))
    if not validation.ok:
        return CarryScanRow(
            opportunity=blocked_carry_opportunity(inputs, validation),
            status="blocked_missing_inputs",
            threshold_met=False,
            min_net_apr=min_net_apr,
            cost_assumptions=assumptions,
            source_health=inputs.source_health,
            metadata=inputs.metadata,
        )
    assert inputs.funding is not None
    assert inputs.basis is not None
    gross_apr = inputs.funding.annualized_rate + inputs.basis.annualized_basis
    net_apr = gross_apr - assumptions.total_cost_apr
    threshold_met = net_apr >= min_net_apr
    direction = "long_spot_short_perp" if inputs.funding.hourly_rate >= 0 else "short_spot_long_perp"
    opportunity = CarryOpportunity(
        asset=inputs.asset,
        venue=Venue.HYPERLIQUID,
        direction=direction,
        net_apr=net_apr,
        gross_apr=gross_apr,
        fee_bps=assumptions.fee_bps,
        slippage_bps=assumptions.slippage_bps,
        buffer_bps=assumptions.volatility_buffer_bps,
        required_fields_missing=[],
    )
    return CarryScanRow(
        opportunity=opportunity,
        status="candidate" if threshold_met else "below_threshold",
        threshold_met=threshold_met,
        min_net_apr=min_net_apr,
        cost_assumptions=assumptions,
        source_health=inputs.source_health,
        metadata=inputs.metadata,
    )


def load_carry_inputs_fixture(path: Path | str) -> list[HyperliquidCarryInput]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("inputs", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("carry input fixture must be a list or {'inputs': [...]}")
    return [_carry_input_from_dict(row) for row in rows]


def _carry_input_from_dict(row: dict[str, Any]) -> HyperliquidCarryInput:
    return HyperliquidCarryInput(
        asset=str(row["asset"]),
        quote=CarryQuote(**row["quote"]),
        funding=FundingSnapshot(**row["funding"]) if row.get("funding") else None,
        basis=BasisSnapshot(**row["basis"]) if row.get("basis") else None,
        metadata=dict(row.get("metadata") or {}),
        source_health={str(k): str(v) for k, v in dict(row.get("source_health") or {}).items()},
    )
