from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.config import FactorWeightsConfig
from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.explanation_evidence import build_explanation_evidence_bundle
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.non_llm_explanation import NonLLMExplanation, build_non_llm_explanation
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import WeightedAssetRank


def test_non_llm_explanation_renders_canonical_evidence_only_summary():
    explanation = build_non_llm_explanation(_evidence())

    assert explanation.text == (
        "coingecko:bitcoin rank=1 weighted_score=0.500000 data_confidence=1.000000 "
        "factors=[trend=raw:0.100000/normalized:0.500000, momentum=raw:0.100000/normalized:0.500000, "
        "mean_reversion=raw:0.100000/normalized:0.500000, risk_adjusted_performance=raw:0.100000/normalized:0.500000] "
        "sources=[https://api.coingecko.com/api/v3/coins/markets@2026-07-14T12:00:00Z]"
    )


def test_non_llm_explanation_fails_closed_for_missing_evidence_or_noncanonical_text():
    evidence = _evidence()

    with pytest.raises(TypeError, match="requires explanation evidence"):
        build_non_llm_explanation(None)
    with pytest.raises(ValueError, match="text is invalid"):
        NonLLMExplanation(evidence, "generated elsewhere")


def _evidence():
    evaluation_time = datetime(2026, 7, 14, 12, tzinfo=UTC)
    provenance = (MarketDataProvenance("coingecko", "https://api.coingecko.com/api/v3/coins/markets", evaluation_time, "a" * 64),)
    confidence = calculate_data_confidence_score(provenance, evaluation_time, timedelta(minutes=10))
    components = tuple(
        ScoreComponent("coingecko", "bitcoin", factor_id, 0.1, 0.5)
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    )
    return build_explanation_evidence_bundle(
        WeightedAssetRank("coingecko", "bitcoin", 1, 0.5), components, FactorWeightsConfig(), confidence, provenance
    )
