from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.vnext.source_disagreement import SourceObservation, detect_source_disagreement

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_source_disagreement_detects_a_spread_above_the_explicit_threshold():
    report = detect_source_disagreement(
        (
            SourceObservation("https://one.example.test/quote", NOW, 100.0),
            SourceObservation("https://two.example.test/quote", NOW, 102.0),
        ),
        NOW,
        threshold=1.0,
    )

    assert report.disagreeing is True
    assert (report.minimum_value, report.maximum_value) == (100.0, 102.0)


@pytest.mark.parametrize(
    "observations,threshold",
    [
        ((), 1.0),
        ((SourceObservation("https://one.example.test/quote", NOW, 100.0),), 1.0),
        (
            (
                SourceObservation("https://one.example.test/quote", NOW, 100.0),
                SourceObservation("https://one.example.test/quote", NOW, 101.0),
            ),
            1.0,
        ),
        (
            (
                SourceObservation("https://one.example.test/quote", NOW + timedelta(seconds=1), 100.0),
                SourceObservation("https://two.example.test/quote", NOW, 101.0),
            ),
            1.0,
        ),
    ],
)
def test_source_disagreement_fails_closed_for_missing_or_malformed_external_data(observations, threshold):
    with pytest.raises((TypeError, ValueError), match="source-disagreement"):
        detect_source_disagreement(observations, NOW, threshold=threshold)


@pytest.mark.parametrize("source_url,value", [("http://example.test/quote", 1.0), ("https://example.test/quote", float("nan"))])
def test_source_observation_rejects_malformed_external_data(source_url, value):
    with pytest.raises(ValueError, match="source-disagreement"):
        SourceObservation(source_url, NOW, value)
