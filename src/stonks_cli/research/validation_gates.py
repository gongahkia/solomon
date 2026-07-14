from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stonks_cli.paths import default_state_dir
from stonks_cli.research.ingestion import (
    DEFAULT_CAPTURE_FIXTURE,
    replay_capture_fixture,
    write_capture_jsonl,
)

CAPTURE_GATE = "capture-7d"
DEFAULT_CAPTURE_STALE_AFTER_SECONDS = 15 * 60
GATE_DEFINITION = {"issue": 13, "title": "7-day Hyperliquid connector clean capture", "target_days": 7}


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
    return default_state_dir() / "validation-gates"


def init_gate(*, state_dir: Path | str | None = None, reset: bool = False, now: datetime | None = None) -> ValidationGateState:
    path = gate_state_path(state_dir=state_dir)
    if path.exists() and not reset:
        return load_gate_state(state_dir=state_dir)
    timestamp = _iso(now or _now())
    state = ValidationGateState(
        gate_id=CAPTURE_GATE,
        title=GATE_DEFINITION["title"],
        issue=GATE_DEFINITION["issue"],
        target_days=GATE_DEFINITION["target_days"],
        started_at_utc=timestamp,
        updated_at_utc=timestamp,
    )
    save_gate_state(state, state_dir=state_dir)
    return state


def gate_state_path(*, state_dir: Path | str | None = None) -> Path:
    root = Path(state_dir) if state_dir is not None else default_validation_dir()
    return root / f"{CAPTURE_GATE}.json"


def load_gate_state(*, state_dir: Path | str | None = None) -> ValidationGateState:
    payload = json.loads(gate_state_path(state_dir=state_dir).read_text(encoding="utf-8"))
    return ValidationGateState(
        gate_id=str(payload["gate_id"]),
        title=str(payload["title"]),
        issue=int(payload["issue"]),
        target_days=int(payload["target_days"]),
        started_at_utc=str(payload["started_at_utc"]),
        updated_at_utc=str(payload["updated_at_utc"]),
        status=str(payload.get("status") or "running"),
        evidence=[ValidationEvidence(kind=row["kind"], timestamp_utc=row["timestamp_utc"], payload=row["payload"]) for row in payload.get("evidence", [])],
    )


def save_gate_state(state: ValidationGateState, *, state_dir: Path | str | None = None) -> Path:
    path = gate_state_path(state_dir=state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def record_capture_probe(
    *,
    state_dir: Path | str | None = None,
    fixture_path: Path | str = DEFAULT_CAPTURE_FIXTURE,
    capture_out_dir: Path | str | None = None,
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    trades, health = replay_capture_fixture(fixture_path)
    output_path = None
    if capture_out_dir is not None:
        output = Path(capture_out_dir) / f"capture-{(now or _now()).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
        write_capture_jsonl(trades, output)
        output_path = str(output)
    return record_capture_health(
        state_dir=state_dir,
        capture_payload={
            "fixture_path": str(fixture_path),
            "capture_out_path": output_path,
            "health": health.to_dict(),
            "decoded_trade_count": len(trades),
            "final_status": "clean_sample" if not health.malformed_messages and not health.dropped_messages else "needs_attention",
        },
        reset=reset,
        now=now,
    )


def record_capture_health(
    *,
    state_dir: Path | str | None = None,
    capture_payload: dict[str, Any],
    reset: bool = False,
    now: datetime | None = None,
) -> ValidationGateState:
    state = init_gate(state_dir=state_dir, reset=reset, now=now)
    timestamp = _iso(now or _now())
    state.evidence.append(ValidationEvidence(kind="capture_health", timestamp_utc=timestamp, payload=capture_payload))
    state.updated_at_utc = timestamp
    state.status = assess_gate(state, now=now).status
    save_gate_state(state, state_dir=state_dir)
    return state


def assess_gate(
    state: ValidationGateState,
    *,
    now: datetime | None = None,
    capture_stale_after_seconds: float = DEFAULT_CAPTURE_STALE_AFTER_SECONDS,
) -> GateAssessment:
    current = now or _now()
    elapsed_days = max(0.0, (current - _parse_ts(state.started_at_utc)).total_seconds() / 86400)
    blockers = [] if elapsed_days >= state.target_days else [f"elapsed_days_below_target:{elapsed_days:.2f}<{state.target_days}"]
    records = [item for item in state.evidence if item.kind == "capture_health"]
    if not records:
        blockers.append("missing_capture_health_evidence")
    for item in records:
        health = item.payload.get("health") or {}
        if int(health.get("malformed_messages") or 0):
            blockers.append("capture_malformed_messages_present")
        if int(health.get("dropped_messages") or 0):
            blockers.append("capture_dropped_messages_present")
    if not any(
        str(item.payload.get("source") or "") == "live_capture"
        and str(item.payload.get("final_status") or "") == "clean_capture"
        and str((item.payload.get("runtime") or {}).get("os") or "").lower() == "linux"
        for item in records
    ):
        blockers.append("capture_missing_clean_linux_live_completion")
    if records and not any(
        str(item.payload.get("source") or "") == "live_capture"
        and str(item.payload.get("final_status") or "") == "clean_capture"
        and str((item.payload.get("runtime") or {}).get("os") or "").lower() == "linux"
        for item in records
    ):
        age = (current - _parse_ts(records[-1].timestamp_utc)).total_seconds()
        if age > capture_stale_after_seconds:
            blockers.append(f"capture_health_stale:{age:.0f}s>{capture_stale_after_seconds:.0f}s")
    blockers = sorted(set(blockers))
    return GateAssessment(CAPTURE_GATE, "passed" if not blockers else "stale" if any("stale" in item for item in blockers) else "running", round(elapsed_days, 4), state.target_days, len(state.evidence), blockers)


def render_gate_report(state: ValidationGateState, *, now: datetime | None = None) -> str:
    assessment = assess_gate(state, now=now)
    lines = [f"# {state.title}", "", f"- GitHub issue: #{state.issue}", f"- Status: `{assessment.status}`", f"- Elapsed days: {assessment.elapsed_days:.2f} / {assessment.target_days}", "", "## Blockers", ""]
    lines.extend(f"- {blocker}" for blocker in assessment.blockers or ["none"])
    return "\n".join(lines) + "\n"


def write_gate_report(state: ValidationGateState, *, report_path: Path | str, now: datetime | None = None) -> Path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_gate_report(state, now=now), encoding="utf-8")
    return path


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
