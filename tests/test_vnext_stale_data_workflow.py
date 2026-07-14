from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.data_freshness import DataFreshnessStatus, monitor_data_freshness
from stonks_cli.vnext.default_deny_execution import DefaultDenyExecutionGateway, ExecutionRequest
from stonks_cli.vnext.errors import VNextExecutionDeniedError
from stonks_cli.vnext.health import HealthCheck, HealthStatus, run_health_checks
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance


def test_stale_data_workflow_propagates_provenance_to_a_failed_health_check_and_execution_denial():
    now = datetime(2026, 7, 14, 3, tzinfo=UTC)
    confidence = calculate_data_confidence_score(
        (
            MarketDataProvenance("coingecko", "https://api.coingecko.com/current", now, "a" * 64),
            MarketDataProvenance("coingecko", "https://api.coingecko.com/stale", now - timedelta(minutes=11), "b" * 64),
        ),
        now,
        timedelta(minutes=10),
    )

    freshness = monitor_data_freshness(confidence, required_fresh_fraction=0.75)
    health = run_health_checks((HealthCheck("source.freshness", lambda: HealthStatus.FAIL if freshness.status is DataFreshnessStatus.STALE else HealthStatus.PASS),))
    decision = DefaultDenyExecutionGateway().evaluate(ExecutionRequest("stale-data-2026-07-14"))

    assert freshness.status is DataFreshnessStatus.STALE
    assert freshness.stale_source_urls == ("https://api.coingecko.com/stale",)
    assert health.status is HealthStatus.FAIL
    assert decision.permitted is False
    with pytest.raises(VNextExecutionDeniedError, match="execution gateway is disabled"):
        decision.require_permitted()
