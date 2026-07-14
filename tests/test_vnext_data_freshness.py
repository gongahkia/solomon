from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.data_freshness import DataFreshnessStatus, monitor_data_freshness
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance


def test_data_freshness_monitor_reports_freshness_against_an_explicit_threshold():
    now = datetime(2026, 7, 14, 3, tzinfo=UTC)
    confidence = calculate_data_confidence_score(
        (
            MarketDataProvenance("coingecko", "https://api.coingecko.com/current", now, "a" * 64),
            MarketDataProvenance("coingecko", "https://api.coingecko.com/stale", now - timedelta(minutes=11), "b" * 64),
        ),
        now,
        timedelta(minutes=10),
    )

    report = monitor_data_freshness(confidence, required_fresh_fraction=0.75)

    assert report.status is DataFreshnessStatus.STALE
    assert report.stale_source_urls == ("https://api.coingecko.com/stale",)


@pytest.mark.parametrize("confidence,required_fraction", [(None, 0.5), ("confidence", 0.5), (None, -0.1), (None, float("nan"))])
def test_data_freshness_monitor_fails_closed_for_missing_or_malformed_external_data(confidence, required_fraction):
    with pytest.raises((TypeError, ValueError), match="data-freshness"):
        monitor_data_freshness(confidence, required_fresh_fraction=required_fraction)  # type: ignore[arg-type]
