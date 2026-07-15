from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.carry.carry_audit import reconcile_carry_state, render_carry_reconciliation_report, write_carry_ledger
from stonks_cli.carry.carry_risk import CarryRiskLimits, CarryRiskState, evaluate_carry_risk
from stonks_cli.carry.carry_scanner import CarryCostAssumptions, calculate_carry_scan_row
from stonks_cli.research.hyperliquid import HyperliquidCarryInput
from stonks_cli.research.models import CarryDecision, CarryPosition, ExecutionMode


@dataclass(frozen=True)
class PaperCarryConfig:
    bankroll_usd: float = 1000.0
    position_notional_usd: float = 100.0
    maker_fee_bps: float = 2.0
    taker_fee_bps: float = 5.0
    slippage_bps: float = 3.0
    missed_fill_probability: float = 0.0
    fill_roll: float = 1.0
    min_margin_buffer: float = 0.20
    min_liquidation_distance: float = 0.15
    max_delta_abs: float = 0.000001
    kill_switch_active: bool = False
    risk_limits: CarryRiskLimits = field(default_factory=CarryRiskLimits)


@dataclass(frozen=True)
class PaperCarryFill:
    leg: str
    side: str
    price: float
    quantity: float
    notional_usd: float
    fee_usd: float
    slippage_usd: float


@dataclass
class PaperCarryPosition:
    asset: str
    spot_qty: float
    perp_qty: float
    entry_spot: float
    entry_perp: float
    entry_basis: float
    notional_usd: float
    opened_at: str
    last_update_at: str
    accrued_funding: float
    fees: float
    slippage: float
    margin_buffer: float
    liquidation_distance: float
    net_delta: float = 0.0
    exit_reason: str | None = None
    closed_at: str | None = None
    realized_pnl_usd: float = 0.0

    def to_carry_position(self) -> CarryPosition:
        return CarryPosition(
            asset=self.asset,
            spot_qty=self.spot_qty,
            perp_qty=self.perp_qty,
            net_delta=self.net_delta,
            entry_basis=self.entry_basis,
            accrued_funding=self.accrued_funding,
            fees=self.fees,
            margin_buffer=self.margin_buffer,
            liquidation_distance=self.liquidation_distance,
        )


@dataclass
class PaperCarryState:
    positions: dict[str, PaperCarryPosition] = field(default_factory=dict)
    closed_positions: list[PaperCarryPosition] = field(default_factory=list)
    decisions: list[CarryDecision] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "closed_positions": [asdict(position) for position in self.closed_positions],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "positions": {asset: asdict(position) for asset, position in self.positions.items()},
        }


@dataclass(frozen=True)
class PaperCarryRunResult:
    state: PaperCarryState
    report: str

    def to_dict(self) -> dict[str, Any]:
        return {"report": self.report, "state": self.state.to_dict()}


class PaperCarryEngine:
    def __init__(
        self,
        *,
        min_net_apr: float,
        scan_costs: CarryCostAssumptions | None = None,
        config: PaperCarryConfig | None = None,
        state: PaperCarryState | None = None,
    ) -> None:
        self.min_net_apr = min_net_apr
        self.scan_costs = scan_costs or CarryCostAssumptions()
        self.config = config or PaperCarryConfig()
        self.state = state or PaperCarryState()

    def process_input(self, inputs: HyperliquidCarryInput) -> CarryDecision:
        timestamp = inputs.quote.timestamp
        if self.config.kill_switch_active:
            return self._record(inputs, action="skip_kill_switch", reason="kill_switch_active", expected_net_apr=0.0)
        if inputs.asset in self.state.positions:
            return self._maybe_exit(inputs)
        scan = calculate_carry_scan_row(
            inputs,
            min_net_apr=self.min_net_apr,
            assumptions=self.scan_costs,
            now=_parse_ts(timestamp),
        )
        if scan.opportunity.gross_apr <= 0:
            return self._record(inputs, action="skip_negative_funding", reason="funding_not_positive", expected_net_apr=scan.opportunity.net_apr)
        if scan.status != "candidate":
            return self._record(inputs, action="skip_below_threshold", reason=scan.status, expected_net_apr=scan.opportunity.net_apr)
        if self.config.fill_roll < self.config.missed_fill_probability:
            return self._record(inputs, action="skip_missed_fill", reason="paper_fill_model_missed", expected_net_apr=scan.opportunity.net_apr)
        assert inputs.quote.spot_mid is not None
        assert inputs.quote.perp_mid is not None
        notional = min(self.config.position_notional_usd, self.config.bankroll_usd)
        quantity = notional / ((inputs.quote.spot_mid + inputs.quote.perp_mid) / 2)
        risk = evaluate_carry_risk(
            CarryRiskState(
                asset=inputs.asset,
                notional_usd=notional,
                net_delta=0.0,
                spot_qty=quantity,
                perp_qty=-quantity,
                margin_buffer=0.35,
                liquidation_distance=0.50,
                websocket_age_seconds=0.0,
                rest_age_seconds=0.0,
            ),
            limits=self.config.risk_limits,
        )
        if not risk.ok:
            return self._record(
                inputs,
                action="skip_risk_firewall",
                reason=",".join(risk.risk_checks),
                expected_net_apr=scan.opportunity.net_apr,
                risk_checks=risk.risk_checks,
                extra={"risk_assessment": risk.to_dict()},
            )
        spot_fill = _fill("spot", "buy", inputs.quote.spot_mid, quantity, self.config.maker_fee_bps, self.config.slippage_bps)
        perp_fill = _fill("perp", "sell", inputs.quote.perp_mid, quantity, self.config.maker_fee_bps, self.config.slippage_bps)
        position = PaperCarryPosition(
            asset=inputs.asset,
            spot_qty=quantity,
            perp_qty=-quantity,
            entry_spot=spot_fill.price,
            entry_perp=perp_fill.price,
            entry_basis=perp_fill.price - spot_fill.price,
            notional_usd=notional,
            opened_at=timestamp,
            last_update_at=timestamp,
            accrued_funding=0.0,
            fees=spot_fill.fee_usd + perp_fill.fee_usd,
            slippage=spot_fill.slippage_usd + perp_fill.slippage_usd,
            margin_buffer=0.35,
            liquidation_distance=0.50,
        )
        self.state.positions[inputs.asset] = position
        return self._record(
            inputs,
            action="paper_open",
            reason="positive_funding_candidate",
            expected_net_apr=scan.opportunity.net_apr,
            risk_checks=["paper_only", "delta_neutral", "threshold_met"],
            extra={"fills": [asdict(spot_fill), asdict(perp_fill)], "position": asdict(position)},
        )

    def accrue_funding(self, *, asset: str, hourly_rate: float, mark_px: float, hours: float = 1.0) -> None:
        position = self.state.positions[asset]
        position.accrued_funding += abs(position.perp_qty) * mark_px * hourly_rate * hours

    def _maybe_exit(self, inputs: HyperliquidCarryInput) -> CarryDecision:
        position = self.state.positions[inputs.asset]
        timestamp = inputs.quote.timestamp
        hours = max(0.0, (_parse_ts(timestamp) - _parse_ts(position.last_update_at)).total_seconds() / 3600)
        if inputs.funding is not None and inputs.quote.mark_mid is not None and hours:
            self.accrue_funding(asset=inputs.asset, hourly_rate=inputs.funding.hourly_rate, mark_px=inputs.quote.mark_mid, hours=hours)
        position.last_update_at = timestamp
        scan = calculate_carry_scan_row(inputs, min_net_apr=self.min_net_apr, assumptions=self.scan_costs, now=_parse_ts(timestamp))
        reason = "stale_data" if any(item.startswith("stale:") for item in scan.opportunity.required_fields_missing) else None
        reason = reason or _exit_reason(position, inputs, scan_net_apr=scan.opportunity.net_apr, min_net_apr=self.min_net_apr, config=self.config)
        if reason is None:
            return self._record(inputs, action="paper_hold", reason="exit_checks_clear", expected_net_apr=scan.opportunity.net_apr)
        return self._close(inputs, reason=reason, expected_net_apr=scan.opportunity.net_apr)

    def _close(self, inputs: HyperliquidCarryInput, *, reason: str, expected_net_apr: float) -> CarryDecision:
        position = self.state.positions.pop(inputs.asset)
        assert inputs.quote.spot_mid is not None
        assert inputs.quote.perp_mid is not None
        spot_exit = _fill("spot", "sell", inputs.quote.spot_mid, abs(position.spot_qty), self.config.taker_fee_bps, self.config.slippage_bps)
        perp_exit = _fill("perp", "buy", inputs.quote.perp_mid, abs(position.perp_qty), self.config.taker_fee_bps, self.config.slippage_bps)
        spot_pnl = (spot_exit.price - position.entry_spot) * position.spot_qty
        perp_pnl = (position.entry_perp - perp_exit.price) * abs(position.perp_qty)
        exit_fees = spot_exit.fee_usd + perp_exit.fee_usd
        exit_slippage = spot_exit.slippage_usd + perp_exit.slippage_usd
        position.fees += exit_fees
        position.slippage += exit_slippage
        position.realized_pnl_usd = spot_pnl + perp_pnl + position.accrued_funding - position.fees - position.slippage
        position.exit_reason = reason
        position.closed_at = inputs.quote.timestamp
        self.state.closed_positions.append(position)
        return self._record(
            inputs,
            action="paper_exit",
            reason=reason,
            expected_net_apr=expected_net_apr,
            risk_checks=["paper_only", reason],
            extra={"fills": [asdict(spot_exit), asdict(perp_exit)], "closed_position": asdict(position)},
        )

    def _record(
        self,
        inputs: HyperliquidCarryInput,
        *,
        action: str,
        reason: str,
        expected_net_apr: float,
        risk_checks: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> CarryDecision:
        payload = {
            "audit": _audit_payload(inputs=inputs, reason=reason, extra=extra or {}),
            "asset": inputs.asset,
            "source_health": inputs.source_health,
            **(extra or {}),
        }
        decision = CarryDecision(
            decision_id=f"paper-carry:{inputs.asset}:{inputs.quote.timestamp}:{action}",
            mode=ExecutionMode.PAPER,
            action=action,
            reason=reason,
            inputs=payload,
            risk_checks=risk_checks or ["paper_only"],
            expected_net_apr=expected_net_apr,
            exit_rule="funding_flip_or_net_apr_or_risk_gate",
            timestamp=inputs.quote.timestamp,
        )
        self.state.decisions.append(decision)
        return decision


def run_paper_carry(
    *,
    inputs: list[HyperliquidCarryInput],
    min_net_apr: float,
    config: PaperCarryConfig | None = None,
    scan_costs: CarryCostAssumptions | None = None,
) -> PaperCarryRunResult:
    engine = PaperCarryEngine(min_net_apr=min_net_apr, config=config, scan_costs=scan_costs)
    for row in inputs:
        engine.process_input(row)
    return PaperCarryRunResult(state=engine.state, report=render_paper_carry_report(engine.state))


def run_paper_carry_for_duration(
    *,
    fetch_inputs: Callable[[], list[HyperliquidCarryInput]],
    min_net_apr: float,
    duration_seconds: float,
    interval_seconds: float,
    config: PaperCarryConfig | None = None,
    scan_costs: CarryCostAssumptions | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[PaperCarryRunResult], None] | None = None,
) -> PaperCarryRunResult:
    if duration_seconds < 0:
        raise ValueError("duration_seconds must be >= 0")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be > 0")
    engine = PaperCarryEngine(min_net_apr=min_net_apr, config=config, scan_costs=scan_costs)
    started_at = monotonic()
    while True:
        for row in fetch_inputs():
            engine.process_input(row)
        result = PaperCarryRunResult(state=engine.state, report=render_paper_carry_report(engine.state))
        if on_cycle:
            on_cycle(result)
        remaining = duration_seconds - (monotonic() - started_at)
        if remaining <= 0:
            return result
        sleep(min(interval_seconds, remaining))


def write_paper_carry_artifacts(
    *,
    result: PaperCarryRunResult,
    state_dir: Path | str,
    report_path: Path | str,
    ledger_path: Path | str,
    heartbeat_path: Path | str | None = None,
    reconciliation_path: Path | str | None = None,
) -> dict[str, str]:
    state_dir = Path(state_dir)
    report_path = Path(report_path)
    ledger_path = Path(ledger_path)
    heartbeat_path = Path(heartbeat_path) if heartbeat_path else state_dir / "carry-stream-heartbeat.json"
    reconciliation_path = Path(reconciliation_path) if reconciliation_path else state_dir / "carry-reconciliation.md"
    state_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    reconciliation_path.parent.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "carry-paper-state.json"
    _atomic_write(state_path, json.dumps(result.state.to_dict(), indent=2, sort_keys=True))
    _atomic_write(report_path, result.report)
    write_carry_ledger(result.state.decisions, ledger_path)
    report = reconcile_carry_state(
        state=result.state,
        ledger_decisions=result.state.decisions,
        venue_positions={asset: position for asset, position in result.state.positions.items()},
    )
    _atomic_write(
        reconciliation_path,
        "# Carry Paper Reconciliation Report\n\n"
        "- Scope: simulated paper positions; not a live-venue account reconciliation.\n"
        + render_carry_reconciliation_report(report).removeprefix("# Carry Reconciliation Report\n\n"),
    )
    source_timestamps = [decision.timestamp for decision in result.state.decisions]
    _atomic_write(
        heartbeat_path,
        json.dumps(
            {
                "source_timestamp": max(source_timestamps) if source_timestamps else None,
                "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
            sort_keys=True,
        ),
    )
    return {
        "heartbeat_path": str(heartbeat_path),
        "ledger_path": str(ledger_path),
        "reconciliation_path": str(reconciliation_path),
        "report_path": str(report_path),
        "state_path": str(state_path),
    }


def render_paper_carry_report(state: PaperCarryState) -> str:
    realized = sum(position.realized_pnl_usd for position in state.closed_positions)
    lines = [
        "# Carry Paper Run",
        "",
        f"- Open positions: {len(state.positions)}",
        f"- Closed positions: {len(state.closed_positions)}",
        f"- Realized PnL USD: {realized:.6f}",
        f"- Decisions: {len(state.decisions)}",
    ]
    if state.closed_positions:
        lines.extend(["", "| Asset | Exit Reason | Accrued Funding | Fees | Slippage | Realized PnL |", "| --- | --- | ---: | ---: | ---: | ---: |"])
        for position in state.closed_positions:
            lines.append(
                f"| {position.asset} | {position.exit_reason} | {position.accrued_funding:.6f} | {position.fees:.6f} | {position.slippage:.6f} | {position.realized_pnl_usd:.6f} |"
            )
    return "\n".join(lines) + "\n"


def _fill(leg: str, side: str, mid: float, quantity: float, fee_bps: float, slippage_bps: float) -> PaperCarryFill:
    direction = 1.0 if side == "buy" else -1.0
    price = mid * (1 + direction * slippage_bps / 10000)
    notional = abs(price * quantity)
    return PaperCarryFill(
        leg=leg,
        side=side,
        price=price,
        quantity=quantity,
        notional_usd=notional,
        fee_usd=notional * fee_bps / 10000,
        slippage_usd=abs(price - mid) * quantity,
    )


def _audit_payload(*, inputs: HyperliquidCarryInput, reason: str, extra: dict[str, Any]) -> dict[str, Any]:
    position = extra.get("closed_position") or extra.get("position") or {}
    return {
        "basis": inputs.basis.basis_abs if inputs.basis is not None else None,
        "exit_reason": reason
        if reason in {"funding_flip", "net_apr_below_threshold", "stale_data", "kill_switch", "kill_switch_active"}
        else None,
        "expected_funding_apr": inputs.funding.annualized_rate if inputs.funding is not None else None,
        "fees_usd": position.get("fees"),
        "margin_buffer": position.get("margin_buffer"),
        "slippage_usd": position.get("slippage"),
    }


def _exit_reason(
    position: PaperCarryPosition,
    inputs: HyperliquidCarryInput,
    *,
    scan_net_apr: float,
    min_net_apr: float,
    config: PaperCarryConfig,
) -> str | None:
    if config.kill_switch_active:
        return "kill_switch"
    if inputs.funding is not None and inputs.funding.hourly_rate < 0:
        return "funding_flip"
    if scan_net_apr < min_net_apr:
        return "net_apr_below_threshold"
    if abs(position.net_delta) > config.max_delta_abs:
        return "delta_drift"
    if position.margin_buffer < config.min_margin_buffer:
        return "margin_buffer"
    if position.liquidation_distance < config.min_liquidation_distance:
        return "liquidation_distance"
    return None


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)
