from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol, runtime_checkable

from stonks_cli.vnext.errors import VNextExternalDataError

_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


@dataclass(frozen=True)
class CanonicalDailyClose:
    day: date
    close_usd: float

    def __post_init__(self) -> None:
        if not isinstance(self.day, date):
            raise TypeError("canonical daily-close date is invalid")
        if not isinstance(self.close_usd, float) or not math.isfinite(self.close_usd) or self.close_usd <= 0:
            raise ValueError("canonical daily-close USD value is invalid")


@dataclass(frozen=True)
class CanonicalPriceSeries:
    provider_id: str
    provider_asset_id: str
    closes: tuple[CanonicalDailyClose, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _IDENTIFIER_PATTERN.fullmatch(self.provider_id):
            raise ValueError("canonical price provider ID is invalid")
        if not isinstance(self.provider_asset_id, str) or not _IDENTIFIER_PATTERN.fullmatch(self.provider_asset_id):
            raise ValueError("canonical price provider asset ID is invalid")
        if not isinstance(self.closes, tuple) or not self.closes or not all(isinstance(close, CanonicalDailyClose) for close in self.closes):
            raise ValueError("canonical daily closes are invalid")
        days = tuple(close.day for close in self.closes)
        if days != tuple(sorted(days)) or len(set(days)) != len(days):
            raise ValueError("canonical daily closes must be chronological and unique")


@runtime_checkable
class CanonicalPriceDataProvider(Protocol):
    provider_id: str

    def list_daily_closes(self, provider_asset_id: str, start: date, end: date) -> Sequence[CanonicalDailyClose]: ...


def fetch_canonical_daily_closes(
    provider: CanonicalPriceDataProvider, provider_asset_id: str, start: date, end: date
) -> CanonicalPriceSeries:
    if not isinstance(provider_asset_id, str) or not _IDENTIFIER_PATTERN.fullmatch(provider_asset_id):
        raise ValueError("canonical price provider asset ID is invalid")
    if not isinstance(start, date) or not isinstance(end, date) or end < start:
        raise ValueError("canonical daily-close range is invalid")
    provider_id = getattr(provider, "provider_id", None)
    getter = getattr(provider, "list_daily_closes", None)
    if not isinstance(provider_id, str) or not callable(getter):
        raise VNextExternalDataError("canonical price provider is incompatible")
    try:
        closes = getter(provider_asset_id, start, end)
    except VNextExternalDataError:
        raise
    except Exception as error:
        raise VNextExternalDataError("canonical price provider is unavailable") from error
    if not isinstance(closes, Sequence) or isinstance(closes, (str, bytes)):
        raise VNextExternalDataError("canonical price provider response is malformed")
    try:
        series = CanonicalPriceSeries(provider_id, provider_asset_id, tuple(closes))
    except (TypeError, ValueError) as error:
        raise VNextExternalDataError("canonical price provider response is malformed") from error
    if tuple(close.day for close in series.closes) != _days_inclusive(start, end):
        raise VNextExternalDataError("canonical price provider response is incomplete")
    return series


def _days_inclusive(start: date, end: date) -> tuple[date, ...]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return tuple(days)
