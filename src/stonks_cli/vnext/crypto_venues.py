from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import as_utc

_PROVIDER_ASSET_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


class CryptoResearchVenue(StrEnum):
    HYPERLIQUID = "hyperliquid"


@dataclass(frozen=True)
class CryptoVenueAssetSupport:
    venue: CryptoResearchVenue
    provider_asset_ids: frozenset[str]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.venue, CryptoResearchVenue):
            raise TypeError("crypto research venue is invalid")
        if not isinstance(self.provider_asset_ids, frozenset) or not self.provider_asset_ids:
            raise ValueError("crypto venue asset support must be non-empty")
        if not all(isinstance(asset_id, str) and _PROVIDER_ASSET_ID_PATTERN.fullmatch(asset_id) for asset_id in self.provider_asset_ids):
            raise ValueError("crypto venue provider asset IDs are invalid")
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))


def filter_crypto_universe_by_supported_venues(
    batch: CryptoMarketCapBatch,
    supports: Sequence[CryptoVenueAssetSupport],
    supported_venues: frozenset[CryptoResearchVenue],
) -> tuple[CryptoMarketCapAsset, ...]:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    if not isinstance(supports, Sequence) or isinstance(supports, (str, bytes)):
        raise TypeError("crypto venue asset support must be a sequence")
    if not isinstance(supported_venues, frozenset) or not supported_venues or not all(
        isinstance(venue, CryptoResearchVenue) for venue in supported_venues
    ):
        raise ValueError("supported crypto research venues are invalid")
    if not all(isinstance(support, CryptoVenueAssetSupport) for support in supports):
        raise VNextExternalDataError("crypto venue asset support is malformed")
    support_by_venue = {support.venue: support for support in supports}
    if len(support_by_venue) != len(supports) or not supported_venues.issubset(support_by_venue):
        raise VNextExternalDataError("crypto venue asset support is incomplete")
    available_asset_ids = set().union(*(support_by_venue[venue].provider_asset_ids for venue in supported_venues))
    return tuple(asset for asset in batch.assets if asset.provider_asset_id in available_asset_ids)
