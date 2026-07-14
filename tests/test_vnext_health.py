from __future__ import annotations

import pytest

from stonks_cli.vnext.health import HealthCheck, HealthResult, HealthStatus, run_health_checks


def test_health_checks_aggregate_deterministically():
    report = run_health_checks(
        (
            HealthCheck("database.connection", lambda: HealthStatus.PASS),
            HealthCheck("source.freshness", lambda: HealthResult("source.freshness", HealthStatus.WARNING, "stale")),
        )
    )

    assert report.status is HealthStatus.WARNING
    assert report.results == (
        HealthResult("database.connection", HealthStatus.PASS, "pass"),
        HealthResult("source.freshness", HealthStatus.WARNING, "stale"),
    )


def test_health_checks_fail_closed_for_exceptions_and_malformed_results():
    def raising_check() -> HealthStatus:
        raise RuntimeError("token-value")

    report = run_health_checks(
        (
            HealthCheck("source.connection", raising_check),
            HealthCheck("source.payload", lambda: "pass"),
        )
    )

    assert report.status is HealthStatus.FAIL
    assert report.results == (
        HealthResult("source.connection", HealthStatus.FAIL, "check_error"),
        HealthResult("source.payload", HealthStatus.FAIL, "invalid_result"),
    )
    assert "token-value" not in str(report)


def test_health_checks_reject_duplicate_registration_names():
    with pytest.raises(ValueError, match="names must be unique"):
        run_health_checks((HealthCheck("database", lambda: HealthStatus.PASS), HealthCheck("database", lambda: HealthStatus.PASS)))
