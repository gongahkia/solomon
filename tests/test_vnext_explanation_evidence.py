from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.config import FactorWeightsConfig
from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.explanation_evidence import build_explanation_evidence_bundle
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import WeightedAssetRank


def test_explanation_evidence_bundle_canonically_binds_rank_components_confidence_and_provenance():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    provenance = (
        MarketDataProvenance("coingecko", "https://api.coingecko.com/markets", evaluation_time, "0" * 64),
        MarketDataProvenance("coingecko", "https://api.coingecko.com/history", evaluation_time, "1" * 64),
    )
    confidence = calculate_data_confidence_score(provenance, evaluation_time, timedelta(minutes=10))
    components = (
        ScoreComponent("coingecko", "bitcoin", "risk_adjusted_performance", 0.1, 0.5),
        ScoreComponent("coingecko", "bitcoin", "mean_reversion", 0.1, 0.5),
        ScoreComponent("coingecko", "bitcoin", "momentum", 0.1, 0.5),
        ScoreComponent("coingecko", "bitcoin", "trend", 0.1, 0.5),
    )

    evidence = build_explanation_evidence_bundle(
        WeightedAssetRank("coingecko", "bitcoin", 1, 0.5), components, FactorWeightsConfig(), confidence, tuple(reversed(provenance))
    )

    assert tuple(component.factor_id for component in evidence.score_components) == (
        "trend",
        "momentum",
        "mean_reversion",
        "risk_adjusted_performance",
    )
    assert tuple(item.source_url for item in evidence.provenance) == (
        "https://api.coingecko.com/history",
        "https://api.coingecko.com/markets",
    )


def test_explanation_evidence_bundle_fails_closed_for_incomplete_or_mismatched_evidence():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    provenance = (MarketDataProvenance("coingecko", "https://api.coingecko.com/markets", evaluation_time, "0" * 64),)
    confidence = calculate_data_confidence_score(provenance, evaluation_time, timedelta(minutes=10))
    components = tuple(
        ScoreComponent("coingecko", "bitcoin", factor_id, 0.1, 0.5)
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    )

    with pytest.raises(ValueError, match="factor components"):
        build_explanation_evidence_bundle(
            WeightedAssetRank("coingecko", "bitcoin", 1, 0.5), components[:-1], FactorWeightsConfig(), confidence, provenance
        )
    with pytest.raises(ValueError, match="components do not match"):
        build_explanation_evidence_bundle(
            WeightedAssetRank("coingecko", "ethereum", 1, 0.5), components, FactorWeightsConfig(), confidence, provenance
        )
    with pytest.raises(ValueError, match="weighted score"):
        build_explanation_evidence_bundle(
            WeightedAssetRank("coingecko", "bitcoin", 1, 0.4), components, FactorWeightsConfig(), confidence, provenance
        )
