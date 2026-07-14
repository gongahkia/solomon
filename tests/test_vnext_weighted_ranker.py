from itertools import permutations

import pytest

from stonks_cli.config import RESEARCH_FACTOR_IDS, FactorWeightsConfig
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import rank_weighted_assets


def test_weighted_ranker_combines_complete_factor_components_by_asset():
    components = (
        ScoreComponent("coingecko", "bitcoin", "trend", 0.3, 0.9),
        ScoreComponent("coingecko", "bitcoin", "momentum", 0.2, 0.8),
        ScoreComponent("coingecko", "bitcoin", "mean_reversion", 0.1, 0.7),
        ScoreComponent("coingecko", "bitcoin", "risk_adjusted_performance", 0.4, 0.6),
        ScoreComponent("coingecko", "ethereum", "trend", 0.1, 0.4),
        ScoreComponent("coingecko", "ethereum", "momentum", 0.2, 0.5),
        ScoreComponent("coingecko", "ethereum", "mean_reversion", 0.3, 0.6),
        ScoreComponent("coingecko", "ethereum", "risk_adjusted_performance", 0.4, 0.7),
    )

    ranks = rank_weighted_assets(components, FactorWeightsConfig())

    assert [(item.provider_asset_id, item.rank, item.weighted_score) for item in ranks] == [
        ("bitcoin", 1, pytest.approx(0.75)),
        ("ethereum", 2, pytest.approx(0.55)),
    ]


def test_weighted_ranker_fails_closed_for_incomplete_duplicate_cross_provider_or_mutated_weights():
    complete = tuple(
        ScoreComponent("coingecko", "bitcoin", factor_id, 0.1, 0.5)
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    )
    weights = FactorWeightsConfig()
    weights.weights["trend"] = 0.5

    with pytest.raises(ValueError, match="every configured factor"):
        rank_weighted_assets(complete[:-1], FactorWeightsConfig())
    with pytest.raises(ValueError, match="duplicate"):
        rank_weighted_assets(complete + (complete[0],), FactorWeightsConfig())
    with pytest.raises(ValueError, match="one provider"):
        rank_weighted_assets(complete + (ScoreComponent("other", "ethereum", "trend", 0.1, 0.5),), FactorWeightsConfig())
    with pytest.raises(ValueError, match="sum to one"):
        rank_weighted_assets(complete, weights)


def test_weighted_ranker_breaks_equal_scores_by_canonical_asset_id_not_input_order():
    components = tuple(
        ScoreComponent("coingecko", asset_id, factor_id, 0.1, 0.5)
        for asset_id in ("ethereum", "bitcoin")
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    )

    ranks = rank_weighted_assets(components, FactorWeightsConfig())

    assert [(item.provider_asset_id, item.rank) for item in ranks] == [("bitcoin", 1), ("ethereum", 2)]


def test_weighted_ranker_is_invariant_to_all_asset_and_factor_input_orderings():
    scores = {"alpha": 0.5, "beta": 0.8, "zeta": 0.8}
    expected = (("beta", 1, 0.8), ("zeta", 2, 0.8), ("alpha", 3, 0.5))

    for asset_ids in permutations(scores):
        for factor_ids in permutations(RESEARCH_FACTOR_IDS):
            components = tuple(
                ScoreComponent("coingecko", asset_id, factor_id, scores[asset_id], scores[asset_id])
                for asset_id in asset_ids
                for factor_id in factor_ids
            )

            assert tuple((item.provider_asset_id, item.rank, item.weighted_score) for item in rank_weighted_assets(components, FactorWeightsConfig())) == expected
