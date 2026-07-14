from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from stonks_cli.vnext.data_confidence import DataConfidenceScore


class DataFreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True)
class DataFreshnessReport:
    provider_id: str
    status: DataFreshnessStatus
    required_fresh_fraction: float
    observed_fresh_fraction: float
    stale_source_urls: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("data-freshness provider ID is invalid")
        if not isinstance(self.status, DataFreshnessStatus):
            raise TypeError("data-freshness status is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) and 0 <= value <= 1 for value in (self.required_fresh_fraction, self.observed_fresh_fraction)):
            raise ValueError("data-freshness fractions are invalid")
        if not isinstance(self.stale_source_urls, tuple) or not all(isinstance(url, str) and url for url in self.stale_source_urls):
            raise ValueError("data-freshness stale sources are invalid")
        if self.stale_source_urls != tuple(sorted(self.stale_source_urls)):
            raise ValueError("data-freshness stale sources are not canonical")
        expected_status = DataFreshnessStatus.FRESH if self.observed_fresh_fraction >= self.required_fresh_fraction else DataFreshnessStatus.STALE
        if self.status is not expected_status:
            raise ValueError("data-freshness status is inconsistent")


def monitor_data_freshness(confidence: DataConfidenceScore, *, required_fresh_fraction: float) -> DataFreshnessReport:
    if not isinstance(confidence, DataConfidenceScore):
        raise TypeError("data-freshness requires data confidence")
    if not isinstance(required_fresh_fraction, float) or not math.isfinite(required_fresh_fraction) or not 0 <= required_fresh_fraction <= 1:
        raise ValueError("data-freshness required fraction is invalid")
    status = DataFreshnessStatus.FRESH if confidence.score >= required_fresh_fraction else DataFreshnessStatus.STALE
    return DataFreshnessReport(
        confidence.provider_id,
        status,
        required_fresh_fraction,
        confidence.score,
        confidence.stale_source_urls,
    )
