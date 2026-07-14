from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch

DEFAULT_STABLECOIN_PROVIDER_ASSET_IDS = frozenset(
    {
        "dai",
        "ethena-usde",
        "first-digital-usd",
        "gemini-dollar",
        "pax-dollar",
        "paypal-usd",
        "tether",
        "true-usd",
        "usd-coin",
    }
)


class StablecoinStatus(StrEnum):
    STABLECOIN = "stablecoin"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class StablecoinClassification:
    asset: CryptoMarketCapAsset
    status: StablecoinStatus

    def __post_init__(self) -> None:
        if not isinstance(self.asset, CryptoMarketCapAsset):
            raise TypeError("stablecoin classification asset is invalid")
        if not isinstance(self.status, StablecoinStatus):
            raise TypeError("stablecoin classification status is invalid")


@dataclass(frozen=True)
class StablecoinClassifier:
    provider_asset_ids: frozenset[str] = DEFAULT_STABLECOIN_PROVIDER_ASSET_IDS

    def __post_init__(self) -> None:
        if not isinstance(self.provider_asset_ids, frozenset) or not self.provider_asset_ids:
            raise ValueError("stablecoin provider asset IDs must be non-empty")
        if not all(isinstance(asset_id, str) and asset_id for asset_id in self.provider_asset_ids):
            raise ValueError("stablecoin provider asset IDs are invalid")

    def classify(self, asset: CryptoMarketCapAsset) -> StablecoinClassification:
        if not isinstance(asset, CryptoMarketCapAsset):
            raise TypeError("crypto market-cap asset is required")
        status = StablecoinStatus.STABLECOIN if asset.provider_asset_id in self.provider_asset_ids else StablecoinStatus.UNCLASSIFIED
        return StablecoinClassification(asset, status)


def classify_stablecoins(
    batch: CryptoMarketCapBatch, classifier: StablecoinClassifier | None = None
) -> tuple[StablecoinClassification, ...]:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    active_classifier = classifier or StablecoinClassifier()
    if not isinstance(active_classifier, StablecoinClassifier):
        raise TypeError("stablecoin classifier is required")
    return tuple(active_classifier.classify(asset) for asset in batch.assets)
