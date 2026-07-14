from datetime import UTC, datetime

import pytest

from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.source_citations import SOURCE_CITATION_SCHEMA_VERSION, SourceCitation


def test_source_citation_round_trips_validated_market_data_provenance():
    provenance = MarketDataProvenance(
        "coingecko",
        "https://api.coingecko.com/api/v3/coins/markets",
        datetime(2026, 7, 14, 12, 30, tzinfo=UTC),
        "a" * 64,
    )

    citation = SourceCitation.from_provenance(provenance)

    assert citation.to_data() == {
        "version": SOURCE_CITATION_SCHEMA_VERSION,
        "provider_id": "coingecko",
        "source_url": "https://api.coingecko.com/api/v3/coins/markets",
        "retrieved_at": "2026-07-14T12:30:00Z",
        "response_sha256": "a" * 64,
    }
    assert SourceCitation.from_data(citation.to_data()) == citation


@pytest.mark.parametrize(
    "data",
    (
        {},
        {"version": 2, "provider_id": "coingecko", "source_url": "https://api.coingecko.com/markets", "retrieved_at": "2026-07-14T12:30:00Z", "response_sha256": "a" * 64},
        {"version": 1, "provider_id": "coingecko", "source_url": "http://api.coingecko.com/markets", "retrieved_at": "2026-07-14T12:30:00Z", "response_sha256": "a" * 64},
        {"version": 1, "provider_id": "coingecko", "source_url": "https://api.coingecko.com/markets", "retrieved_at": "invalid", "response_sha256": "a" * 64},
    ),
)
def test_source_citation_fails_closed_for_invalid_schema_or_provenance(data):
    with pytest.raises(ValueError):
        SourceCitation.from_data(data)
