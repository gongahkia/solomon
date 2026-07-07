from __future__ import annotations

import json
import os
import platform
import shutil
import socket
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from stonks_cli.config import AppConfig
from stonks_cli.whalemirror.hyperliquid import HYPERLIQUID_INFO_URL, HyperliquidOrderClient

REQUIRED_ALERT_EVENTS = {"kill_switch", "stale_data", "ledger_mismatch", "service_restart"}


@dataclass(frozen=True)
class CarryHealthCheck:
    name: str
    status: str
    detail: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CarryHealthReport:
    status: str
    checks: list[CarryHealthCheck]
    generated_at: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "generated_at": self.generated_at,
            "ok": self.ok,
            "status": self.status,
        }


def build_carry_health_report(
    *,
    cfg: AppConfig,
    state_dir: Path | str,
    ledger_path: Path | str,
    stream_heartbeat_path: Path | str | None = None,
    reconciliation_path: Path | str | None = None,
    now: datetime | None = None,
    skip_network: bool = False,
    max_stream_age_seconds: float = 120.0,
    min_disk_free_mb: float = 512.0,
    min_ram_free_mb: float = 128.0,
    max_clock_drift_seconds: float = 5.0,
    client: HyperliquidOrderClient | None = None,
) -> CarryHealthReport:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    state_dir = Path(state_dir)
    ledger_path = Path(ledger_path)
    heartbeat_path = Path(stream_heartbeat_path) if stream_heartbeat_path else state_dir / "carry-stream-heartbeat.json"
    reconciliation = Path(reconciliation_path) if reconciliation_path else state_dir / "carry-reconciliation.md"
    checks = [
        _host_check(),
        _storage_check(state_dir=state_dir, min_disk_free_mb=min_disk_free_mb),
        _memory_check(min_ram_free_mb=min_ram_free_mb),
        _clock_check(now=now, skip_network=skip_network, max_clock_drift_seconds=max_clock_drift_seconds),
        _network_check(skip_network=skip_network),
        _venue_check(skip_network=skip_network, client=client),
        _stream_check(path=heartbeat_path, now=now, max_age_seconds=max_stream_age_seconds),
        _ledger_check(ledger_path=ledger_path, reconciliation_path=reconciliation),
        _alert_check(cfg=cfg),
    ]
    status = "fail" if any(check.status == "fail" for check in checks) else "warn" if any(check.status == "warn" for check in checks) else "ok"
    return CarryHealthReport(status=status, checks=checks, generated_at=now.isoformat().replace("+00:00", "Z"))


def render_carry_health_report(report: CarryHealthReport) -> str:
    lines = [
        "# CarryMirror Health",
        "",
        f"- Status: {report.status}",
        f"- Generated: {report.generated_at}",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in report.checks:
        lines.append(f"| {check.name} | {check.status} | {_cell(check.detail)} |")
    return "\n".join(lines) + "\n"


def _host_check() -> CarryHealthCheck:
    data = {
        "machine": platform.machine(),
        "node": platform.node(),
        "python": platform.python_version(),
        "system": platform.system(),
    }
    return CarryHealthCheck("host", "ok", f"{data['system']} {data['machine']}", data)


def _storage_check(*, state_dir: Path, min_disk_free_mb: float) -> CarryHealthCheck:
    target = state_dir if state_dir.exists() else state_dir.parent if state_dir.parent.exists() else Path(".")
    usage = shutil.disk_usage(target)
    free_mb = usage.free / 1024 / 1024
    status = "ok" if free_mb >= min_disk_free_mb else "fail"
    return CarryHealthCheck("storage", status, f"{free_mb:.1f} MiB free", {"free_mb": free_mb, "path": str(target)})


def _memory_check(*, min_ram_free_mb: float) -> CarryHealthCheck:
    free_mb = _available_ram_mb()
    if free_mb is None:
        return CarryHealthCheck("ram", "warn", "available RAM unavailable")
    status = "ok" if free_mb >= min_ram_free_mb else "fail"
    return CarryHealthCheck("ram", status, f"{free_mb:.1f} MiB available", {"available_mb": free_mb})


def _clock_check(*, now: datetime, skip_network: bool, max_clock_drift_seconds: float) -> CarryHealthCheck:
    if skip_network:
        return CarryHealthCheck("time_sync", "warn", "clock drift unchecked with --skip-network")
    try:
        remote = _hyperliquid_date_header()
        drift = abs((now - remote).total_seconds())
    except Exception as e:
        return CarryHealthCheck("time_sync", "warn", f"clock drift unavailable: {e}")
    status = "ok" if drift <= max_clock_drift_seconds else "fail"
    return CarryHealthCheck("time_sync", status, f"{drift:.3f}s drift", {"drift_seconds": drift})


def _network_check(*, skip_network: bool) -> CarryHealthCheck:
    if skip_network:
        return CarryHealthCheck("network", "warn", "network check skipped")
    try:
        with socket.create_connection(("api.hyperliquid.xyz", 443), timeout=3.0):
            pass
    except Exception as e:
        return CarryHealthCheck("network", "fail", f"api.hyperliquid.xyz unreachable: {e}")
    return CarryHealthCheck("network", "ok", "api.hyperliquid.xyz:443 reachable")


def _venue_check(*, skip_network: bool, client: HyperliquidOrderClient | None) -> CarryHealthCheck:
    if skip_network:
        return CarryHealthCheck("venue_api", "warn", "venue API check skipped")
    try:
        mids = (client or HyperliquidOrderClient(timeout=3.0)).fetch_all_mids()
    except Exception as e:
        return CarryHealthCheck("venue_api", "fail", f"Hyperliquid allMids failed: {e}")
    missing = [asset for asset in ("BTC", "ETH") if asset not in mids]
    if missing:
        return CarryHealthCheck("venue_api", "warn", f"missing mids: {', '.join(missing)}", {"sample_size": len(mids)})
    return CarryHealthCheck("venue_api", "ok", "BTC and ETH mids available", {"sample_size": len(mids)})


def _stream_check(*, path: Path, now: datetime, max_age_seconds: float) -> CarryHealthCheck:
    if not path.exists():
        return CarryHealthCheck("stream", "warn", f"heartbeat missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_ts = payload.get("timestamp") or payload.get("updated_at")
        observed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).astimezone(UTC)
    except Exception:
        observed = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    age = (now - observed).total_seconds()
    status = "ok" if age <= max_age_seconds else "fail"
    return CarryHealthCheck("stream", status, f"{age:.1f}s old", {"age_seconds": age, "path": str(path)})


def _ledger_check(*, ledger_path: Path, reconciliation_path: Path) -> CarryHealthCheck:
    if not ledger_path.exists():
        return CarryHealthCheck("ledger", "warn", f"ledger missing: {ledger_path}")
    if ledger_path.stat().st_size <= 0:
        return CarryHealthCheck("ledger", "fail", f"ledger empty: {ledger_path}")
    if reconciliation_path.exists() and "Blocks live progression: true" in reconciliation_path.read_text(encoding="utf-8"):
        return CarryHealthCheck("ledger", "fail", f"reconciliation blocks live: {reconciliation_path}")
    return CarryHealthCheck("ledger", "ok", f"ledger present: {ledger_path}", {"path": str(ledger_path)})


def _alert_check(*, cfg: AppConfig) -> CarryHealthCheck:
    carry = cfg.carrymirror
    events = set(carry.alert_events)
    missing_events = sorted(REQUIRED_ALERT_EVENTS - events)
    if carry.alert_sink == "disabled":
        status = "fail" if missing_events else "warn"
        detail = "alerts disabled"
    elif carry.alert_sink == "telegram":
        missing_envs = [name for name in (carry.telegram_bot_token_env, carry.telegram_chat_id_env) if not os.getenv(name)]
        status = "fail" if missing_envs or missing_events else "ok"
        detail = "telegram configured" if status == "ok" else f"missing: {', '.join(missing_envs + missing_events)}"
    else:
        missing_envs = [name for name in (carry.email_smtp_url_env, carry.email_to_env) if not os.getenv(name)]
        status = "fail" if missing_envs or missing_events else "ok"
        detail = "email configured" if status == "ok" else f"missing: {', '.join(missing_envs + missing_events)}"
    return CarryHealthCheck("alerts", status, detail, {"events": sorted(events), "sink": carry.alert_sink})


def _available_ram_mb() -> float | None:
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None
    return float(pages * page_size) / 1024 / 1024


def _hyperliquid_date_header() -> datetime:
    request = Request(
        HYPERLIQUID_INFO_URL,
        data=b'{"type":"allMids"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=3.0) as response:
        header = response.headers.get("Date")
    if not header:
        raise ValueError("missing Date header")
    return parsedate_to_datetime(header).astimezone(UTC)


def _cell(value: str) -> str:
    return value.replace("|", "/")
