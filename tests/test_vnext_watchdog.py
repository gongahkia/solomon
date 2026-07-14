from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.health import HealthCheck, HealthStatus
from stonks_cli.vnext.watchdog import WatchdogRunStatus, WatchdogService

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_watchdog_service_runs_health_checks_then_skips_until_its_interval_elapses():
    calls: list[str] = []
    service = WatchdogService((HealthCheck("opend.availability", lambda: calls.append("check") or HealthStatus.PASS),), timedelta(minutes=1))

    first = service.poll(NOW)
    skipped = service.poll(NOW + timedelta(seconds=30))
    second = service.poll(NOW + timedelta(minutes=1))

    assert (first.status, skipped.status, second.status) == (WatchdogRunStatus.EXECUTED, WatchdogRunStatus.SKIPPED, WatchdogRunStatus.EXECUTED)
    assert calls == ["check", "check"]


@pytest.mark.parametrize("checks,interval", [((), timedelta(minutes=1)), ((HealthCheck("opend.availability", lambda: HealthStatus.PASS),), timedelta())])
def test_watchdog_service_fails_closed_for_missing_or_malformed_configuration(checks, interval):
    with pytest.raises(ValueError, match="watchdog"):
        WatchdogService(checks, interval)


def test_watchdog_service_rejects_time_moving_backwards():
    service = WatchdogService((HealthCheck("opend.availability", lambda: HealthStatus.PASS),), timedelta(minutes=1))
    service.poll(NOW)

    with pytest.raises(ValueError, match="time moved backwards"):
        service.poll(NOW - timedelta(seconds=1))
