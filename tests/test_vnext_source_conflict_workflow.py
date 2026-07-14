from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.default_deny_execution import DefaultDenyExecutionGateway, ExecutionRequest
from stonks_cli.vnext.errors import VNextExecutionDeniedError
from stonks_cli.vnext.health import HealthCheck, HealthStatus, run_health_checks
from stonks_cli.vnext.source_disagreement import SourceObservation, detect_source_disagreement


def test_source_conflict_workflow_fails_health_and_keeps_execution_denied():
    now = datetime(2026, 7, 14, 3, tzinfo=UTC)
    disagreement = detect_source_disagreement(
        (
            SourceObservation("https://z.example.test/quote", now, 102.0),
            SourceObservation("https://a.example.test/quote", now, 100.0),
        ),
        now,
        threshold=1.0,
    )
    health = run_health_checks((HealthCheck("source.conflict", lambda: HealthStatus.FAIL if disagreement.disagreeing else HealthStatus.PASS),))
    decision = DefaultDenyExecutionGateway().evaluate(ExecutionRequest("source-conflict-2026-07-14"))

    assert disagreement.disagreeing is True
    assert disagreement.source_urls == ("https://a.example.test/quote", "https://z.example.test/quote")
    assert health.status is HealthStatus.FAIL
    with pytest.raises(VNextExecutionDeniedError, match="execution gateway is disabled"):
        decision.require_permitted()
