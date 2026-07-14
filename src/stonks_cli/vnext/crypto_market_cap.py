from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import as_utc

_ASSET_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*\Z")
_PROVIDER_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SYMBOL_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9._-]*\Z")


@dataclass(frozen=True)
class CryptoMarketCapAsset:
    provider_asset_id: str
    symbol: str
    name: str
    market_cap_usd: float
    market_cap_rank: int
    reported_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.provider_asset_id, str) or not _ASSET_ID_PATTERN.fullmatch(self.provider_asset_id):
            raise ValueError("crypto provider asset ID is invalid")
        if not isinstance(self.symbol, str) or not _SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("crypto symbol is invalid")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("crypto asset name is invalid")
        if not isinstance(self.market_cap_usd, float) or not math.isfinite(self.market_cap_usd) or self.market_cap_usd <= 0:
            raise ValueError("crypto market cap must be a positive finite USD value")
        if not isinstance(self.market_cap_rank, int) or isinstance(self.market_cap_rank, bool) or self.market_cap_rank < 1:
            raise ValueError("crypto market cap rank must be positive")
        object.__setattr__(self, "reported_at", as_utc(self.reported_at))


@dataclass(frozen=True)
class CryptoMarketCapBatch:
    provider_id: str
    assets: tuple[CryptoMarketCapAsset, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID_PATTERN.fullmatch(self.provider_id):
            raise ValueError("crypto market-cap provider ID is invalid")
        if not isinstance(self.assets, tuple) or not self.assets or not all(
            isinstance(asset, CryptoMarketCapAsset) for asset in self.assets
        ):
            raise ValueError("crypto market-cap assets are invalid")
        if len({asset.provider_asset_id for asset in self.assets}) != len(self.assets):
            raise ValueError("crypto provider asset IDs must be unique")
        if len({asset.symbol for asset in self.assets}) != len(self.assets):
            raise ValueError("crypto symbols must be unique")
        ranks = tuple(asset.market_cap_rank for asset in self.assets)
        if ranks != tuple(sorted(ranks)) or len(set(ranks)) != len(ranks):
            raise ValueError("crypto market-cap assets must use unique ascending ranks")


@runtime_checkable
class CryptoMarketCapProvider(Protocol):
    provider_id: str

    def list_market_caps(self, limit: int) -> Sequence[CryptoMarketCapAsset]: ...


def fetch_crypto_market_caps(provider: CryptoMarketCapProvider, limit: int) -> CryptoMarketCapBatch:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise ValueError("crypto market-cap limit must be an integer from 1 through 100")
    provider_id = getattr(provider, "provider_id", None)
    getter = getattr(provider, "list_market_caps", None)
    if not isinstance(provider_id, str) or not callable(getter):
        raise VNextExternalDataError("crypto market-cap provider is incompatible")
    try:
        assets = getter(limit)
    except VNextExternalDataError:
        raise
    except Exception as error:
        raise VNextExternalDataError("crypto market-cap provider is unavailable") from error
    if not isinstance(assets, Sequence) or isinstance(assets, (str, bytes)) or len(assets) != limit:
        raise VNextExternalDataError("crypto market-cap provider response is incomplete")
    try:
        return CryptoMarketCapBatch(provider_id, tuple(assets))
    except (TypeError, ValueError) as error:
        raise VNextExternalDataError("crypto market-cap provider response is malformed") from error
