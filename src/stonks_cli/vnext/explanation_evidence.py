from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.config import RESEARCH_FACTOR_IDS, FactorWeightsConfig
from stonks_cli.vnext.data_confidence import DataConfidenceScore, calculate_data_confidence_score
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance
from stonks_cli.vnext.score_components import ScoreComponent
from stonks_cli.vnext.weighted_ranker import WeightedAssetRank


@dataclass(frozen=True)
class ExplanationEvidenceBundle:
    rank: WeightedAssetRank
    score_components: tuple[ScoreComponent, ...]
    factor_weights: tuple[tuple[str, float], ...]
    data_confidence: DataConfidenceScore
    provenance: tuple[MarketDataProvenance, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.rank, WeightedAssetRank):
            raise TypeError("explanation evidence rank is invalid")
        if not isinstance(self.score_components, tuple) or not all(isinstance(component, ScoreComponent) for component in self.score_components):
            raise ValueError("explanation evidence factor components are invalid")
        if tuple(component.factor_id for component in self.score_components) != RESEARCH_FACTOR_IDS:
            raise ValueError("explanation evidence factor components are invalid")
        if any(component.provider_id != self.rank.provider_id or component.provider_asset_id != self.rank.provider_asset_id for component in self.score_components):
            raise ValueError("explanation evidence components do not match rank")
        if not isinstance(self.factor_weights, tuple) or tuple(factor_id for factor_id, _ in self.factor_weights) != RESEARCH_FACTOR_IDS:
            raise ValueError("explanation evidence factor weights are invalid")
        weights = FactorWeightsConfig(weights=dict(self.factor_weights)).weights
        expected_score = sum(component.normalized_score * weights[component.factor_id] for component in self.score_components)
        if not math.isclose(self.rank.weighted_score, expected_score, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("explanation evidence weighted score is inconsistent")
        if not isinstance(self.data_confidence, DataConfidenceScore):
            raise TypeError("explanation evidence data confidence is invalid")
        if self.data_confidence.provider_id != self.rank.provider_id:
            raise ValueError("explanation evidence confidence does not match rank")
        if not isinstance(self.provenance, tuple) or not self.provenance or not all(isinstance(item, MarketDataProvenance) for item in self.provenance):
            raise ValueError("explanation evidence provenance is invalid")
        if tuple(item.source_url for item in self.provenance) != tuple(sorted(item.source_url for item in self.provenance)):
            raise ValueError("explanation evidence provenance is not canonical")
        if calculate_data_confidence_score(self.provenance, self.data_confidence.evaluated_at, self.data_confidence.maximum_age) != self.data_confidence:
            raise ValueError("explanation evidence provenance does not match confidence")


def build_explanation_evidence_bundle(
    rank: WeightedAssetRank,
    score_components: Sequence[ScoreComponent],
    factor_weights: FactorWeightsConfig,
    data_confidence: DataConfidenceScore,
    provenance: Sequence[MarketDataProvenance],
) -> ExplanationEvidenceBundle:
    if not isinstance(rank, WeightedAssetRank):
        raise TypeError("explanation evidence rank is required")
    if not isinstance(score_components, Sequence) or isinstance(score_components, (str, bytes)):
        raise ValueError("explanation evidence score components are invalid")
    if not all(isinstance(component, ScoreComponent) for component in score_components):
        raise TypeError("explanation evidence requires score components")
    if not isinstance(factor_weights, FactorWeightsConfig):
        raise TypeError("explanation evidence factor weights are required")
    if not isinstance(data_confidence, DataConfidenceScore):
        raise TypeError("explanation evidence data confidence is required")
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)):
        raise ValueError("explanation evidence provenance is invalid")
    if not all(isinstance(item, MarketDataProvenance) for item in provenance):
        raise TypeError("explanation evidence requires market-data provenance")
    canonical_weights = FactorWeightsConfig(weights=factor_weights.weights).ordered_items()
    factor_index = {factor_id: index for index, factor_id in enumerate(RESEARCH_FACTOR_IDS)}
    return ExplanationEvidenceBundle(
        rank,
        tuple(sorted(score_components, key=lambda component: factor_index.get(component.factor_id, len(factor_index)))),
        canonical_weights,
        data_confidence,
        tuple(sorted(provenance, key=lambda item: item.source_url)),
    )
