from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.health import HealthCheck, HealthReport, run_health_checks


class WatchdogRunStatus(StrEnum):
    EXECUTED = "executed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class WatchdogRun:
    status: WatchdogRunStatus
    observed_at: datetime
    report: HealthReport | None

    def __post_init__(self) -> None:
        if not isinstance(self.status, WatchdogRunStatus):
            raise TypeError("watchdog run status is invalid")
        if self.status is WatchdogRunStatus.EXECUTED and not isinstance(self.report, HealthReport):
            raise ValueError("executed watchdog run requires a health report")
        if self.status is WatchdogRunStatus.SKIPPED and self.report is not None:
            raise ValueError("skipped watchdog run must not have a health report")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


class WatchdogService:
    def __init__(self, checks: Sequence[HealthCheck], interval: timedelta) -> None:
        if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks or not all(isinstance(check, HealthCheck) for check in checks):
            raise ValueError("watchdog checks are invalid")
        if not isinstance(interval, timedelta) or interval <= timedelta():
            raise ValueError("watchdog interval is invalid")
        self._checks = tuple(checks)
        self._interval = interval
        self._last_run_at: datetime | None = None

    def poll(self, observed_at: datetime) -> WatchdogRun:
        timestamp = as_utc(observed_at)
        if self._last_run_at is not None:
            if timestamp < self._last_run_at:
                raise ValueError("watchdog time moved backwards")
            if timestamp - self._last_run_at < self._interval:
                return WatchdogRun(WatchdogRunStatus.SKIPPED, timestamp, None)
        report = run_health_checks(self._checks)
        self._last_run_at = timestamp
        return WatchdogRun(WatchdogRunStatus.EXECUTED, timestamp, report)
