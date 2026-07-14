from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from stonks_cli.vnext.foundation import as_utc


@dataclass(frozen=True)
class SourceObservation:
    source_url: str
    observed_at: datetime
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.source_url, str):
            raise ValueError("source-disagreement URL is invalid")
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("source-disagreement URL is invalid")
        if not isinstance(self.value, float) or not math.isfinite(self.value):
            raise ValueError("source-disagreement value is invalid")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


@dataclass(frozen=True)
class SourceDisagreementReport:
    evaluated_at: datetime
    minimum_value: float
    maximum_value: float
    threshold: float
    disagreeing: bool
    source_urls: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.minimum_value, self.maximum_value, self.threshold)) or self.threshold < 0:
            raise ValueError("source-disagreement values are invalid")
        if self.minimum_value > self.maximum_value:
            raise ValueError("source-disagreement range is invalid")
        if not isinstance(self.disagreeing, bool) or self.disagreeing is not (self.maximum_value - self.minimum_value > self.threshold):
            raise ValueError("source-disagreement status is inconsistent")
        if not isinstance(self.source_urls, tuple) or len(self.source_urls) < 2 or not all(isinstance(url, str) and url for url in self.source_urls):
            raise ValueError("source-disagreement sources are invalid")
        if self.source_urls != tuple(sorted(self.source_urls)) or len(set(self.source_urls)) != len(self.source_urls):
            raise ValueError("source-disagreement sources are not canonical")


def detect_source_disagreement(
    observations: Sequence[SourceObservation],
    evaluated_at: datetime,
    *,
    threshold: float,
) -> SourceDisagreementReport:
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)) or len(observations) < 2:
        raise ValueError("source-disagreement requires at least two observations")
    if not all(isinstance(observation, SourceObservation) for observation in observations):
        raise TypeError("source-disagreement observations are invalid")
    evaluation_time = as_utc(evaluated_at)
    if any(observation.observed_at > evaluation_time for observation in observations):
        raise ValueError("source-disagreement cannot evaluate future observations")
    if not isinstance(threshold, float) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("source-disagreement threshold is invalid")
    source_urls = tuple(sorted(observation.source_url for observation in observations))
    if len(set(source_urls)) != len(source_urls):
        raise ValueError("source-disagreement sources must be unique")
    values = tuple(observation.value for observation in observations)
    minimum_value = min(values)
    maximum_value = max(values)
    return SourceDisagreementReport(
        evaluation_time,
        minimum_value,
        maximum_value,
        threshold,
        maximum_value - minimum_value > threshold,
        source_urls,
    )
