from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from stonks_cli.config import RESEARCH_FACTOR_IDS, FactorWeightsConfig
from stonks_cli.vnext.score_components import ScoreComponent


@dataclass(frozen=True)
class WeightedAssetRank:
    provider_id: str
    provider_asset_id: str
    rank: int
    weighted_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("weighted-rank provider ID is invalid")
        if not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("weighted-rank provider asset ID is invalid")
        if not isinstance(self.rank, int) or isinstance(self.rank, bool) or self.rank < 1:
            raise ValueError("weighted-rank position is invalid")
        if not isinstance(self.weighted_score, float) or not math.isfinite(self.weighted_score) or not 0 <= self.weighted_score <= 1:
            raise ValueError("weighted-rank score is invalid")


def rank_weighted_assets(
    components: Sequence[ScoreComponent], factor_weights: FactorWeightsConfig
) -> tuple[WeightedAssetRank, ...]:
    if not isinstance(components, Sequence) or isinstance(components, (str, bytes)) or not components:
        raise ValueError("weighted ranking requires score components")
    if not all(isinstance(component, ScoreComponent) for component in components):
        raise TypeError("weighted ranking requires score components")
    if not isinstance(factor_weights, FactorWeightsConfig):
        raise TypeError("weighted ranking requires factor weights")
    weights = FactorWeightsConfig(weights=factor_weights.weights).weights
    if len({component.provider_id for component in components}) != 1:
        raise ValueError("weighted ranking requires one provider")
    grouped: dict[str, dict[str, ScoreComponent]] = {}
    for component in components:
        asset_components = grouped.setdefault(component.provider_asset_id, {})
        if component.factor_id in asset_components:
            raise ValueError("weighted ranking has duplicate asset factor components")
        asset_components[component.factor_id] = component
    weighted_scores = tuple(
        (asset_id, sum(asset_components[factor_id].normalized_score * weights[factor_id] for factor_id in RESEARCH_FACTOR_IDS))
        for asset_id, asset_components in grouped.items()
        if _require_complete_components(asset_components)
    )
    provider_id = components[0].provider_id
    return tuple(
        WeightedAssetRank(provider_id, asset_id, rank, weighted_score)
        for rank, (asset_id, weighted_score) in enumerate(sorted(weighted_scores, key=lambda item: (-item[1], item[0])), start=1)
    )


def _require_complete_components(components: dict[str, ScoreComponent]) -> bool:
    if set(components) != set(RESEARCH_FACTOR_IDS):
        raise ValueError("weighted ranking requires every configured factor per asset")
    return True
