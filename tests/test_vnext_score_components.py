import math

import pytest

from stonks_cli.vnext.score_components import ScoreComponent


def test_score_component_preserves_canonical_factor_evidence_and_normalized_score():
    component = ScoreComponent("coingecko", "bitcoin", "trend", 0.12, 0.75)

    assert component == ScoreComponent("coingecko", "bitcoin", "trend", 0.12, 0.75)


@pytest.mark.parametrize(
    "provider_id,asset_id,factor_id,raw_value,normalized_score",
    (
        ("", "bitcoin", "trend", 0.12, 0.75),
        ("coingecko", "", "trend", 0.12, 0.75),
        ("coingecko", "bitcoin", "unknown", 0.12, 0.75),
        ("coingecko", "bitcoin", "trend", math.nan, 0.75),
        ("coingecko", "bitcoin", "trend", 0.12, -0.01),
        ("coingecko", "bitcoin", "trend", 0.12, 1.01),
    ),
)
def test_score_component_fails_closed_for_invalid_evidence(provider_id, asset_id, factor_id, raw_value, normalized_score):
    with pytest.raises(ValueError):
        ScoreComponent(provider_id, asset_id, factor_id, raw_value, normalized_score)
