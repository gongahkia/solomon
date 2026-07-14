from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.config import FactorWeightsConfig
from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.explanation_evidence import build_explanation_evidence_bundle
from stonks_cli.vnext.llm_summary_boundary import LLMSummaryBoundary, create_llm_summary_boundary
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import WeightedAssetRank


def test_llm_summary_boundary_exposes_only_evidence_derived_citations():
    evidence = _evidence()

    boundary = create_llm_summary_boundary(evidence)

    assert boundary.evidence == evidence
    assert boundary.operation == "summarize_evidence"
    assert boundary.citations[0].source_url == "https://api.coingecko.com/api/v3/coins/markets"


def test_llm_summary_boundary_fails_closed_for_non_summary_operations_or_unbound_citations():
    evidence = _evidence()

    with pytest.raises(ValueError, match="only permits"):
        LLMSummaryBoundary(evidence, create_llm_summary_boundary(evidence).citations, "rank_assets")
    with pytest.raises(ValueError, match="do not match"):
        LLMSummaryBoundary(evidence, ())


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
