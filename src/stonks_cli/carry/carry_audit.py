from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from stonks_cli.research.models import CarryDecision


@dataclass(frozen=True)
class CarryReconciliationMismatch:
    name: str
    inputs: dict[str, Any]


@dataclass(frozen=True)
class CarryReconciliationReport:
    ok: bool
    blocks_live: bool
    mismatches: list[CarryReconciliationMismatch]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocks_live": self.blocks_live,
            "mismatches": [asdict(mismatch) for mismatch in self.mismatches],
            "ok": self.ok,
        }


def render_carry_ledger(decisions: list[CarryDecision]) -> str:
    lines = [
        "# Carry Audit Ledger",
        "",
        "| Timestamp | Asset | Action | Expected Funding APR | Expected Net APR | Fees | Slippage | Basis | Margin Buffer | Risk Checks | Exit Reason |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for decision in decisions:
        row = carry_ledger_row(decision)
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row["timestamp"]),
                    _cell(row["asset"]),
                    _cell(row["action"]),
                    _pct(row["expected_funding_apr"]),
                    _pct(row["expected_net_apr"]),
                    _money(row["fees_usd"]),
                    _money(row["slippage_usd"]),
                    _number(row["basis"]),
                    _number(row["margin_buffer"]),
                    _cell(", ".join(row["risk_checks"])),
                    _cell(row["exit_reason"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_carry_ledger(decisions: list[CarryDecision], path: Path | str) -> Path:
    use_path = Path(path)
    use_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=use_path.parent, delete=False) as handle:
        handle.write(render_carry_ledger(decisions))
        temporary = Path(handle.name)
    os.replace(temporary, use_path)
    return use_path


def carry_ledger_row(decision: CarryDecision) -> dict[str, Any]:
    audit = dict(decision.inputs.get("audit") or {})
    return {
        "action": decision.action,
        "asset": decision.inputs.get("asset", ""),
        "basis": audit.get("basis"),
        "exit_reason": audit.get("exit_reason") or (decision.reason if decision.action in {"paper_exit", "skip_kill_switch"} else ""),
        "expected_funding_apr": audit.get("expected_funding_apr"),
        "expected_net_apr": decision.expected_net_apr,
        "fees_usd": audit.get("fees_usd"),
        "margin_buffer": audit.get("margin_buffer"),
        "risk_checks": list(decision.risk_checks),
        "slippage_usd": audit.get("slippage_usd"),
        "timestamp": decision.timestamp,
    }


def reconcile_carry_state(
    *,
    state: Any,
    ledger_decisions: list[CarryDecision],
    venue_positions: dict[str, Any] | None,
) -> CarryReconciliationReport:
    venue_positions = venue_positions or {}
    open_assets = set(getattr(state, "positions", {}).keys())
    venue_assets = set(venue_positions.keys())
    mismatches: list[CarryReconciliationMismatch] = []
    opened_in_ledger = {str(decision.inputs.get("asset")) for decision in ledger_decisions if decision.action == "paper_open"}
    exited_in_ledger = {str(decision.inputs.get("asset")) for decision in ledger_decisions if decision.action == "paper_exit"}
    for asset in sorted(open_assets - venue_assets):
        mismatches.append(_mismatch("venue_missing_position", asset=asset))
    for asset in sorted(venue_assets - open_assets):
        mismatches.append(_mismatch("state_missing_position", asset=asset))
    for asset in sorted(open_assets - opened_in_ledger):
        mismatches.append(_mismatch("ledger_missing_open", asset=asset))
    for position in getattr(state, "closed_positions", []):
        asset = str(getattr(position, "asset", ""))
        if asset and asset not in exited_in_ledger:
            mismatches.append(_mismatch("ledger_missing_exit", asset=asset, exit_reason=getattr(position, "exit_reason", None)))
    return CarryReconciliationReport(ok=not mismatches, blocks_live=bool(mismatches), mismatches=mismatches)


def render_carry_reconciliation_report(report: CarryReconciliationReport) -> str:
    lines = [
        "# Carry Reconciliation Report",
        "",
        f"- OK: {str(report.ok).lower()}",
        f"- Blocks live progression: {str(report.blocks_live).lower()}",
        "",
        "| Mismatch | Inputs |",
        "| --- | --- |",
    ]
    if not report.mismatches:
        lines.append("| none | {} |")
    for mismatch in report.mismatches:
        lines.append(f"| {_cell(mismatch.name)} | {_cell(json.dumps(mismatch.inputs, sort_keys=True))} |")
    return "\n".join(lines) + "\n"


def _mismatch(name: str, **inputs: Any) -> CarryReconciliationMismatch:
    return CarryReconciliationMismatch(name=name, inputs=inputs)


def _pct(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value) * 100:.2f}%"


def _money(value: Any) -> str:
    if value is None:
        return ""
    number = float(value)
    return f"-${abs(number):.2f}" if number < 0 else f"${number:.2f}"


def _number(value: Any) -> str:
    return "" if value is None else f"{float(value):.6f}"


def _cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "/")
