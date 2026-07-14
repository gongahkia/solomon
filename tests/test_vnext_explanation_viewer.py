from datetime import UTC, datetime, timedelta

import pytest

from stonks_cli.config import FactorWeightsConfig
from stonks_cli.vnext.data_confidence import calculate_data_confidence_score
from stonks_cli.vnext.explanation_evidence import build_explanation_evidence_bundle
from stonks_cli.vnext.explanation_viewer import InteractiveExplanationViewer
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import WeightedAssetRank


def test_interactive_explanation_viewer_selects_and_renders_canonical_factor_detail():
    viewer = InteractiveExplanationViewer(_evidence())

    selected = viewer.select_factor("momentum")

    assert selected.selected_component == ScoreComponent("fixture", "bitcoin", "momentum", 0.2, 0.5)
    assert selected.render() == (
        "EXPLANATION VIEWER\n"
        "asset: fixture:bitcoin\n"
        "rank: 1\n"
        "weighted_score: 0.500000\n"
        "data_confidence: 1.000000\n"
        "available_factors: trend, momentum, mean_reversion, risk_adjusted_performance\n"
        "selected_factor: momentum\n"
        "raw_value: 0.200000\n"
        "normalized_score: 0.500000\n"
        "weight: 0.250000\n"
        "contribution: 0.125000\n"
        "sources:\n"
        "- https://example.test/market@2026-07-14T12:00:00Z"
    )


def test_interactive_explanation_viewer_fails_closed_for_missing_evidence_or_unknown_factor():
    with pytest.raises(TypeError, match="requires evidence"):
        InteractiveExplanationViewer(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="factor"):
        InteractiveExplanationViewer(_evidence()).select_factor("unsupported")


def _evidence():
    evaluated_at = datetime(2026, 7, 14, 12, tzinfo=UTC)
    provenance = (MarketDataProvenance("fixture", "https://example.test/market", evaluated_at, "0" * 64),)
    confidence = calculate_data_confidence_score(provenance, evaluated_at, timedelta(minutes=10))
    components = tuple(
        ScoreComponent("fixture", "bitcoin", factor_id, 0.2, 0.5)
        for factor_id in ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
    )
    return build_explanation_evidence_bundle(
        WeightedAssetRank("fixture", "bitcoin", 1, 0.5), components, FactorWeightsConfig(), confidence, provenance
    )
