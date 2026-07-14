from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.config import RESEARCH_FACTOR_IDS


@dataclass(frozen=True)
class ScoreComponent:
    provider_id: str
    provider_asset_id: str
    factor_id: str
    raw_value: float
    normalized_score: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("score-component provider ID is invalid")
        if not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("score-component provider asset ID is invalid")
        if not isinstance(self.factor_id, str) or self.factor_id not in RESEARCH_FACTOR_IDS:
            raise ValueError("score-component factor ID is invalid")
        if not isinstance(self.raw_value, float) or not math.isfinite(self.raw_value):
            raise ValueError("score-component raw value is invalid")
        if not isinstance(self.normalized_score, float) or not math.isfinite(self.normalized_score) or not 0 <= self.normalized_score <= 1:
            raise ValueError("score-component normalized score is invalid")
