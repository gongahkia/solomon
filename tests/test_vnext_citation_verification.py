from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.citation_verification import verify_source_citation
from stonks_cli.vnext.source_citations import SourceCitation


def test_citation_verification_revalidates_url_and_accepts_fresh_timestamp():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    citation = SourceCitation("coingecko", "https://api.coingecko.com/api/v3/coins/markets", evaluation_time - timedelta(minutes=5), "a" * 64)

    verification = verify_source_citation(citation, evaluation_time, timedelta(minutes=10))

    assert verification.citation == citation
    assert verification.age == timedelta(minutes=5)


def test_citation_verification_fails_closed_for_stale_future_or_invalid_windows():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    stale = SourceCitation("coingecko", "https://api.coingecko.com/stale", evaluation_time - timedelta(minutes=11), "a" * 64)
    future = SourceCitation("coingecko", "https://api.coingecko.com/future", evaluation_time + timedelta(seconds=1), "b" * 64)

    with pytest.raises(ValueError, match="stale"):
        verify_source_citation(stale, evaluation_time, timedelta(minutes=10))
    with pytest.raises(ValueError, match="future"):
        verify_source_citation(future, evaluation_time, timedelta(minutes=10))
    with pytest.raises(ValueError, match="maximum age"):
        verify_source_citation(stale, evaluation_time, timedelta(0))
