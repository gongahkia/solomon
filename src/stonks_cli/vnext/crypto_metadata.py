from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapBatch
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import as_utc

_IDENTIFIER_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")


@dataclass(frozen=True)
class CryptoAssetPlatform:
    platform_id: str
    contract_address: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.platform_id, str) or not _IDENTIFIER_PATTERN.fullmatch(self.platform_id):
            raise ValueError("crypto asset platform ID is invalid")
        if self.contract_address is not None and (not isinstance(self.contract_address, str) or not self.contract_address.strip()):
            raise ValueError("crypto asset platform contract address is invalid")


@dataclass(frozen=True)
class CryptoAssetMetadata:
    provider_asset_id: str
    category_ids: tuple[str, ...]
    platforms: tuple[CryptoAssetPlatform, ...]
    reported_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.provider_asset_id, str) or not _IDENTIFIER_PATTERN.fullmatch(self.provider_asset_id):
            raise ValueError("crypto metadata provider asset ID is invalid")
        if not isinstance(self.category_ids, tuple) or not all(
            isinstance(category_id, str) and _IDENTIFIER_PATTERN.fullmatch(category_id) for category_id in self.category_ids
        ):
            raise ValueError("crypto metadata category IDs are invalid")
        if self.category_ids != tuple(sorted(set(self.category_ids))):
            raise ValueError("crypto metadata category IDs must be sorted and unique")
        if not isinstance(self.platforms, tuple) or not all(isinstance(platform, CryptoAssetPlatform) for platform in self.platforms):
            raise ValueError("crypto metadata platforms are invalid")
        platform_ids = tuple(platform.platform_id for platform in self.platforms)
        if platform_ids != tuple(sorted(set(platform_ids))):
            raise ValueError("crypto metadata platforms must be sorted and unique")
        object.__setattr__(self, "reported_at", as_utc(self.reported_at))


@runtime_checkable
class CryptoAssetMetadataProvider(Protocol):
    provider_id: str

    def list_asset_metadata(self, provider_asset_ids: Sequence[str]) -> Sequence[CryptoAssetMetadata]: ...


def ingest_crypto_asset_metadata(
    batch: CryptoMarketCapBatch, provider: CryptoAssetMetadataProvider
) -> tuple[CryptoAssetMetadata, ...]:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    provider_id = getattr(provider, "provider_id", None)
    getter = getattr(provider, "list_asset_metadata", None)
    if provider_id != batch.provider_id or not callable(getter):
        raise VNextExternalDataError("crypto metadata provider is incompatible")
    asset_ids = tuple(asset.provider_asset_id for asset in batch.assets)
    try:
        metadata = getter(asset_ids)
    except VNextExternalDataError:
        raise
    except Exception as error:
        raise VNextExternalDataError("crypto metadata provider is unavailable") from error
    if not isinstance(metadata, Sequence) or isinstance(metadata, (str, bytes)) or len(metadata) != len(asset_ids):
        raise VNextExternalDataError("crypto metadata provider response is incomplete")
    if not all(isinstance(item, CryptoAssetMetadata) for item in metadata):
        raise VNextExternalDataError("crypto metadata provider response is malformed")
    metadata_by_id = {item.provider_asset_id: item for item in metadata}
    if len(metadata_by_id) != len(metadata) or set(metadata_by_id) != set(asset_ids):
        raise VNextExternalDataError("crypto metadata provider response is incomplete")
    return tuple(metadata_by_id[asset_id] for asset_id in asset_ids)
