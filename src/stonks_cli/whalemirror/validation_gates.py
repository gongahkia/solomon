from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from stonks_cli.paths import default_state_dir
from stonks_cli.whalemirror.attribution import DEFAULT_ATTRIBUTION_FIXTURE, rank_wallets_from_fixture
from stonks_cli.whalemirror.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    IngestionHealth,
    replay_capture_fixture,
    write_capture_jsonl,
)
from stonks_cli.whalemirror.paper_mirror import (
    DEFAULT_PAPER_MIRROR_FIXTURE,
    PaperMirrorConfig,
    replay_paper_mirror_fixture,
)

DEFAULT_LIVE_VALIDATION_FIXTURE = Path("tests/fixtures/whalemirror/live-validation.json")

CAPTURE_GATE = "capture-7d"
PAPER_GATE = "paper-30d"
LIVE_GATE = "live-60d"
DEFAULT_CAPTURE_STALE_AFTER_SECONDS = 15 * 60

GATE_DEFINITIONS: dict[str, dict[str, Any]] = {
    CAPTURE_GATE: {
        "issue": 13,
        "title": "7-day Hyperliquid connector clean capture",
        "target_days": 7,
    },
    PAPER_GATE: {
        "issue": 14,
        "title": "30-day top-5 Hyperliquid paper mirror gate",
        "target_days": 30,
    },
    LIVE_GATE: {
        "issue": 10,
        "title": "60-day live validation, slippage, and scale gate",
        "target_days": 60,
    },
}


@dataclass
class ValidationEvidence:
    kind: str
    timestamp_utc: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationGateState:
    gate_id: str
    title: str
    issue: int
    target_days: int
    started_at_utc: str
    updated_at_utc: str
    status: str = "running"
    evidence: list[ValidationEvidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


@dataclass(frozen=True)
class GateAssessment:
    gate_id: str
    status: str
    elapsed_days: float
    target_days: int
    evidence_count: int
    blockers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_validation_dir() -> Path:
    return default_state_dir() / "whalemirror-validation"


def init_gate(
    gate_id: str,
    *,
    state_dir: Path | str | None = None,
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    definition = _definition(gate_id)
    path = gate_state_path(gate_id, state_dir=state_dir)
    if path.exists() and not reset:
        return load_gate_state(gate_id, state_dir=state_dir)
    timestamp = _iso(now or _now())
    state = ValidationGateState(
        gate_id=gate_id,
        title=str(definition["title"]),
        issue=int(definition["issue"]),
        target_days=int(definition["target_days"]),
        started_at_utc=timestamp,
        updated_at_utc=timestamp,
    )
    save_gate_state(state, state_dir=state_dir)
    return state


def gate_state_path(gate_id: str, *, state_dir: Path | str | None = None) -> Path:
    return _state_dir(state_dir) / f"{gate_id}.json"


def load_gate_state(gate_id: str, *, state_dir: Path | str | None = None) -> ValidationGateState:
    path = gate_state_path(gate_id, state_dir=state_dir)
    payload = json.loads(path.read_text(encoding="utf-8"))
    evidence = [ValidationEvidence(kind=row["kind"], timestamp_utc=row["timestamp_utc"], payload=row["payload"]) for row in payload.get("evidence", [])]
    return ValidationGateState(
        gate_id=str(payload["gate_id"]),
        title=str(payload["title"]),
        issue=int(payload["issue"]),
        target_days=int(payload["target_days"]),
        started_at_utc=str(payload["started_at_utc"]),
        updated_at_utc=str(payload["updated_at_utc"]),
        status=str(payload.get("status") or "running"),
        evidence=evidence,
    )


def save_gate_state(state: ValidationGateState, *, state_dir: Path | str | None = None) -> Path:
    path = gate_state_path(state.gate_id, state_dir=state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def append_evidence(
    state: ValidationGateState,
    *,
    kind: str,
    payload: dict[str, Any],
    state_dir: Path | str | None = None,
    now: datetime | None = None,
) -> ValidationGateState:
    timestamp = _iso(now or _now())
    state.evidence.append(ValidationEvidence(kind=kind, timestamp_utc=timestamp, payload=payload))
    state.updated_at_utc = timestamp
    state.status = assess_gate(state, now=now).status
    save_gate_state(state, state_dir=state_dir)
    return state


def record_capture_probe(
    *,
    state_dir: Path | str | None = None,
    fixture_path: Path | str = DEFAULT_CAPTURE_FIXTURE,
    capture_out_dir: Path | str | None = None,
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    state = init_gate(CAPTURE_GATE, state_dir=state_dir, reset=reset, now=now)
    trades, health = replay_capture_fixture(fixture_path)
    out_path: str | None = None
    if capture_out_dir is not None:
        target = Path(capture_out_dir) / f"capture-{_file_timestamp(now or _now())}.jsonl"
        write_capture_jsonl(trades, target)
        out_path = str(target)
    return append_evidence(
        state,
        kind="capture_health",
        payload={
            "fixture_path": str(fixture_path),
            "capture_out_path": out_path,
            "health": health.to_dict(),
            "decoded_trade_count": len(trades),
            "final_status": _capture_probe_status(health),
        },
        state_dir=state_dir,
        now=now,
    )


def record_capture_health(
    *,
    state_dir: Path | str | None = None,
    capture_payload: dict[str, Any],
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    state = init_gate(CAPTURE_GATE, state_dir=state_dir, reset=reset, now=now)
    return append_evidence(
        state,
        kind="capture_health",
        payload=capture_payload,
        state_dir=state_dir,
        now=now,
    )


def record_paper_probe(
    *,
    state_dir: Path | str | None = None,
    fixture_path: Path | str = DEFAULT_PAPER_MIRROR_FIXTURE,
    rankings_fixture: Path | str = DEFAULT_ATTRIBUTION_FIXTURE,
    config: PaperMirrorConfig | None = None,
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    state = init_gate(PAPER_GATE, state_dir=state_dir, reset=reset, now=now)
    rankings = rank_wallets_from_fixture(rankings_fixture, limit=5)
    replay = replay_paper_mirror_fixture(fixture_path=fixture_path, rankings=rankings, config=config)
    decisions = [decision.ledger_record.to_dict() for decision in replay.decisions]
    return append_evidence(
        state,
        kind="paper_tearsheet",
        payload={
            "fixture_path": str(fixture_path),
            "rankings_fixture": str(rankings_fixture),
            "tearsheet": replay.tearsheet,
            "decision_count": len(decisions),
            "risk_controls": _decision_controls(decisions),
            "final_status": "sample_recorded",
        },
        state_dir=state_dir,
        now=now,
    )


def record_live_probe(
    *,
    state_dir: Path | str | None = None,
    fixture_path: Path | str = DEFAULT_LIVE_VALIDATION_FIXTURE,
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    state = init_gate(LIVE_GATE, state_dir=state_dir, reset=reset, now=now)
    payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    latency = latency_report(payload.get("latency_samples") or [])
    slippage = slippage_report(payload.get("slippage_samples") or [])
    scale_gate = scale_gate_report(payload.get("scale_gate") or {})
    return append_evidence(
        state,
        kind="live_validation",
        payload={
            "fixture_path": str(fixture_path),
            "latency_report": latency,
            "slippage_report": slippage,
            "scale_gate": scale_gate,
            "final_status": "sample_recorded",
        },
        state_dir=state_dir,
        now=now,
    )


def assess_gate(
    state: ValidationGateState,
    *,
    now: datetime | None = None,
    capture_stale_after_seconds: float = DEFAULT_CAPTURE_STALE_AFTER_SECONDS,
) -> GateAssessment:
    use_now = now or _now()
    elapsed_days = max(0.0, (_parse_ts(_iso(use_now)) - _parse_ts(state.started_at_utc)).total_seconds() / 86400)
    blockers = _elapsed_blockers(elapsed_days, state.target_days)
    if state.gate_id == CAPTURE_GATE:
        blockers.extend(_capture_blockers(state, now=use_now, stale_after_seconds=capture_stale_after_seconds))
    elif state.gate_id == PAPER_GATE:
        blockers.extend(_paper_blockers(state))
    elif state.gate_id == LIVE_GATE:
        blockers.extend(_live_blockers(state))
    status = "passed" if not blockers else "stale" if _has_stale_blocker(blockers) else "running"
    return GateAssessment(
        gate_id=state.gate_id,
        status=status,
        elapsed_days=round(elapsed_days, 4),
        target_days=state.target_days,
        evidence_count=len(state.evidence),
        blockers=blockers,
    )


def render_gate_report(state: ValidationGateState, *, now: datetime | None = None) -> str:
    assessment = assess_gate(state, now=now)
    lines = [
        f"# {state.title}",
        "",
        f"- GitHub issue: #{state.issue}",
        f"- Gate id: `{state.gate_id}`",
        f"- Status: `{assessment.status}`",
        f"- Elapsed days: {assessment.elapsed_days:.2f} / {assessment.target_days}",
        f"- Evidence entries: {assessment.evidence_count}",
        "",
        "## Blockers",
        "",
    ]
    if assessment.blockers:
        lines.extend(f"- {blocker}" for blocker in assessment.blockers)
    else:
        lines.append("- none")
    lines.extend(["", "## Evidence", ""])
    for item in state.evidence:
        lines.append(f"### {item.timestamp_utc} - {item.kind}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(item.payload, indent=2, sort_keys=True))
        lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_gate_report(
    state: ValidationGateState,
    *,
    report_path: Path | str,
    now: datetime | None = None,
) -> Path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gate_report(state, now=now), encoding="utf-8")
    return path


def latency_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [
        float(row["submitted_at_ms"]) - float(row["detected_at_ms"])
        for row in samples
        if row.get("submitted_at_ms") is not None and row.get("detected_at_ms") is not None
    ]
    failures = [row for row in samples if str(row.get("status") or "ok") != "ok"]
    return {
        "sample_count": len(samples),
        "p50_ms": round(median(latencies), 4) if latencies else 0.0,
        "p95_ms": round(_percentile(latencies, 95), 4) if latencies else 0.0,
        "failure_count": len(failures),
        "drop_context": [row.get("failure") or row.get("status") for row in failures],
        "reframe_required": bool(latencies and _percentile(latencies, 95) > 800),
    }


def slippage_report(samples: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for row in samples:
        paper_px = float(row["paper_px"])
        live_px = float(row["live_px"])
        side = str(row.get("side") or "buy").lower()
        adverse = (live_px - paper_px) if side == "buy" else (paper_px - live_px)
        rows.append({**row, "slippage_bps": round((adverse / paper_px) * 10000, 4) if paper_px else 0.0})
    bps = [float(row["slippage_bps"]) for row in rows]
    return {
        "sample_count": len(rows),
        "avg_slippage_bps": round(sum(bps) / len(bps), 4) if bps else 0.0,
        "max_slippage_bps": round(max(bps), 4) if bps else 0.0,
        "rows": rows,
    }


def scale_gate_report(payload: dict[str, Any]) -> dict[str, Any]:
    current_cap = float(payload.get("current_max_live_order_notional_usd", 50.0))
    requested_cap = float(payload.get("requested_max_live_order_notional_usd", current_cap))
    green_weeks = int(payload.get("green_weeks", 0))
    required_green_weeks = int(payload.get("required_green_weeks", 7))
    scale_gate_satisfied = green_weeks >= required_green_weeks
    effective_cap = requested_cap if scale_gate_satisfied else min(current_cap, requested_cap)
    return {
        "current_max_live_order_notional_usd": current_cap,
        "requested_max_live_order_notional_usd": requested_cap,
        "effective_max_live_order_notional_usd": effective_cap,
        "green_weeks": green_weeks,
        "required_green_weeks": required_green_weeks,
        "scale_gate_satisfied": scale_gate_satisfied,
        "auto_raise_blocked": not scale_gate_satisfied and requested_cap > current_cap,
    }


def _definition(gate_id: str) -> dict[str, Any]:
    if gate_id not in GATE_DEFINITIONS:
        raise ValueError(f"unknown validation gate: {gate_id}")
    return GATE_DEFINITIONS[gate_id]


def _state_dir(state_dir: Path | str | None) -> Path:
    return Path(state_dir) if state_dir is not None else default_validation_dir()


def _capture_probe_status(health: IngestionHealth) -> str:
    if health.malformed_messages or health.dropped_messages:
        return "needs_attention"
    return "clean_sample"


def _capture_blockers(
    state: ValidationGateState,
    *,
    now: datetime,
    stale_after_seconds: float,
) -> list[str]:
    blockers = _missing_evidence_blocker(state, "capture_health")
    has_clean_live_completion = False
    latest_running_live_capture: ValidationEvidence | None = None
    for item in state.evidence:
        if item.kind != "capture_health":
            continue
        health = item.payload.get("health") or {}
        source = str(item.payload.get("source") or "fixture")
        final_status = str(item.payload.get("final_status") or "")
        runtime = item.payload.get("runtime") or {}
        runtime_os = str(runtime.get("os") or "")
        if source == "live_capture" and final_status == "running":
            latest_running_live_capture = item
        if source == "live_capture" and final_status == "clean_capture":
            has_clean_live_completion = True
        if source == "live_capture" and runtime_os and runtime_os.lower() != "linux":
            blockers.append("capture_not_run_on_linux_operator_host")
        if int(health.get("malformed_messages") or 0) > 0:
            blockers.append("capture_malformed_messages_present")
        if int(health.get("dropped_messages") or 0) > 0:
            blockers.append("capture_dropped_messages_present")
        if final_status in {"failed", "interrupted", "needs_attention", "max_reconnects_exceeded"}:
            blockers.append("capture_sample_needs_attention")
    if latest_running_live_capture is not None:
        age_seconds = (_parse_ts(_iso(now)) - _parse_ts(latest_running_live_capture.timestamp_utc)).total_seconds()
        if age_seconds > stale_after_seconds:
            blockers.append(f"capture_health_stale:{age_seconds:.0f}s>{stale_after_seconds:.0f}s")
    if not has_clean_live_completion:
        blockers.append("capture_missing_clean_linux_live_completion")
    return sorted(set(blockers))


def _paper_blockers(state: ValidationGateState) -> list[str]:
    blockers = _missing_evidence_blocker(state, "paper_tearsheet")
    for item in state.evidence:
        if item.kind != "paper_tearsheet":
            continue
        tearsheet = item.payload.get("tearsheet") or {}
        controls = set(item.payload.get("risk_controls") or [])
        if int(tearsheet.get("closed_trades") or 0) == 0:
            blockers.append("paper_no_closed_trades")
        if int(tearsheet.get("wins") or 0) == 0 or int(tearsheet.get("losses") or 0) == 0:
            blockers.append("paper_tearsheet_missing_win_or_loss")
        for required in {"paper_mirror_open", "stop_loss", "cooldown"}:
            if required not in controls:
                blockers.append(f"paper_missing_{required}_evidence")
    return sorted(set(blockers))


def _live_blockers(state: ValidationGateState) -> list[str]:
    blockers = _missing_evidence_blocker(state, "live_validation")
    for item in state.evidence:
        if item.kind != "live_validation":
            continue
        latency = item.payload.get("latency_report") or {}
        slippage = item.payload.get("slippage_report") or {}
        scale = item.payload.get("scale_gate") or {}
        if int(latency.get("sample_count") or 0) == 0:
            blockers.append("live_missing_latency_samples")
        if int(slippage.get("sample_count") or 0) == 0:
            blockers.append("live_missing_slippage_samples")
        if scale.get("auto_raise_blocked") is not True and scale.get("scale_gate_satisfied") is not True:
            blockers.append("live_scale_gate_guard_not_proven")
    return sorted(set(blockers))


def _missing_evidence_blocker(state: ValidationGateState, kind: str) -> list[str]:
    return [] if any(item.kind == kind for item in state.evidence) else [f"missing_{kind}_evidence"]


def _elapsed_blockers(elapsed_days: float, target_days: int) -> list[str]:
    if elapsed_days >= target_days:
        return []
    return [f"elapsed_days_below_target:{elapsed_days:.2f}<{target_days}"]


def _has_stale_blocker(blockers: list[str]) -> bool:
    return any(blocker.startswith("capture_health_stale") for blocker in blockers)


def _decision_controls(decisions: list[dict[str, Any]]) -> list[str]:
    controls: set[str] = set()
    for record in decisions:
        decision = str(record.get("decision") or "")
        metadata = record.get("metadata") or {}
        if decision:
            controls.add(decision)
        if metadata.get("risk_control"):
            controls.add(str(metadata["risk_control"]))
        risk_controls = metadata.get("risk_controls") or {}
        if risk_controls:
            controls.add("risk_cap")
    return sorted(controls)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _file_timestamp(value: datetime) -> str:
    return _iso(value).replace(":", "").replace("-", "").replace(".", "").replace("Z", "Z")
