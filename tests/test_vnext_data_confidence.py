from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance


def test_data_confidence_is_the_fraction_of_fresh_unique_sources():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    current = MarketDataProvenance("coingecko", "https://api.coingecko.com/current", evaluation_time - timedelta(minutes=5), "0" * 64)
    stale = MarketDataProvenance("coingecko", "https://api.coingecko.com/stale", evaluation_time - timedelta(minutes=15), "1" * 64)

    confidence = calculate_data_confidence_score((stale, current), evaluation_time, timedelta(minutes=10))

    assert confidence.fresh_source_count == 1
    assert confidence.stale_source_urls == ("https://api.coingecko.com/stale",)
    assert confidence.score == 0.5


def test_data_confidence_fails_closed_for_missing_duplicate_mixed_or_future_provenance():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    current = MarketDataProvenance("coingecko", "https://api.coingecko.com/current", evaluation_time, "0" * 64)
    other_provider = MarketDataProvenance("other", "https://example.com/current", evaluation_time, "1" * 64)
    future = MarketDataProvenance("coingecko", "https://api.coingecko.com/future", evaluation_time + timedelta(seconds=1), "2" * 64)

    with pytest.raises(ValueError, match="requires provenance"):
        calculate_data_confidence_score((), evaluation_time, timedelta(minutes=10))
    with pytest.raises(ValueError, match="unique sources"):
        calculate_data_confidence_score((current, current), evaluation_time, timedelta(minutes=10))
    with pytest.raises(ValueError, match="one provider"):
        calculate_data_confidence_score((current, other_provider), evaluation_time, timedelta(minutes=10))
    with pytest.raises(ValueError, match="future"):
        calculate_data_confidence_score((future,), evaluation_time, timedelta(minutes=10))
