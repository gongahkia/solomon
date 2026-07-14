from __future__ import annotations

import math
from dataclasses import dataclass

from stonks_cli.vnext.stablecoins import StablecoinClassification, StablecoinStatus


@dataclass(frozen=True)
class StablecoinRailAllocation:
    account_id: str
    classification: StablecoinClassification
    amount_usd: float

    def __post_init__(self) -> None:
        if not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("stablecoin rail account ID is invalid")
        if not isinstance(self.classification, StablecoinClassification) or self.classification.status is not StablecoinStatus.STABLECOIN:
            raise ValueError("stablecoin rail classification is invalid")
        if not isinstance(self.amount_usd, float) or not math.isfinite(self.amount_usd) or self.amount_usd < 0:
            raise ValueError("stablecoin rail amount is invalid")
