from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance


@dataclass(frozen=True)
class DataConfidenceScore:
    provider_id: str
    evaluated_at: datetime
    maximum_age: timedelta
    source_count: int
    fresh_source_count: int
    stale_source_urls: tuple[str, ...]
    score: float

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("data-confidence provider ID is invalid")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        if not isinstance(self.maximum_age, timedelta) or self.maximum_age <= timedelta(0):
            raise ValueError("data-confidence maximum age is invalid")
        if not isinstance(self.source_count, int) or self.source_count < 1:
            raise ValueError("data-confidence source count is invalid")
        if not isinstance(self.fresh_source_count, int) or not 0 <= self.fresh_source_count <= self.source_count:
            raise ValueError("data-confidence fresh source count is invalid")
        if not isinstance(self.stale_source_urls, tuple) or not all(isinstance(url, str) and url for url in self.stale_source_urls):
            raise ValueError("data-confidence stale sources are invalid")
        if len(self.stale_source_urls) != self.source_count - self.fresh_source_count or self.stale_source_urls != tuple(sorted(self.stale_source_urls)):
            raise ValueError("data-confidence stale sources are inconsistent")
        if not isinstance(self.score, float) or not math.isfinite(self.score) or not 0 <= self.score <= 1:
            raise ValueError("data-confidence score is invalid")
        if self.score != self.fresh_source_count / self.source_count:
            raise ValueError("data-confidence score is inconsistent")


def calculate_data_confidence_score(
    provenance: Sequence[MarketDataProvenance], evaluated_at: datetime, maximum_age: timedelta
) -> DataConfidenceScore:
    if not isinstance(provenance, Sequence) or isinstance(provenance, (str, bytes)) or not provenance:
        raise ValueError("data confidence requires provenance")
    if not all(isinstance(item, MarketDataProvenance) for item in provenance):
        raise TypeError("data confidence requires market-data provenance")
    evaluation_time = as_utc(evaluated_at)
    if not isinstance(maximum_age, timedelta) or maximum_age <= timedelta(0):
        raise ValueError("data-confidence maximum age is invalid")
    if len({item.provider_id for item in provenance}) != 1:
        raise ValueError("data confidence requires one provider")
    if len({item.source_url for item in provenance}) != len(provenance):
        raise ValueError("data confidence requires unique sources")
    if any(item.retrieved_at > evaluation_time for item in provenance):
        raise ValueError("data confidence cannot evaluate future provenance")
    stale_source_urls = tuple(sorted(item.source_url for item in provenance if evaluation_time - item.retrieved_at > maximum_age))
    fresh_source_count = len(provenance) - len(stale_source_urls)
    return DataConfidenceScore(
        provenance[0].provider_id,
        evaluation_time,
        maximum_age,
        len(provenance),
        fresh_source_count,
        stale_source_urls,
        fresh_source_count / len(provenance),
    )
