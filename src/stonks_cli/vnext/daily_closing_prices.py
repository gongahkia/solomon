from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapBatch
from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.price_data import CanonicalPriceDataProvider, CanonicalPriceSeries, fetch_canonical_daily_closes


@dataclass(frozen=True)
class DailyClosingPriceIngestion:
    provider_id: str
    start: date
    end: date
    series: tuple[CanonicalPriceSeries, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id:
            raise ValueError("daily closing-price provider ID is invalid")
        if not isinstance(self.start, date) or not isinstance(self.end, date) or self.end < self.start:
            raise ValueError("daily closing-price range is invalid")
        if not isinstance(self.series, tuple) or not self.series or not all(isinstance(item, CanonicalPriceSeries) for item in self.series):
            raise ValueError("daily closing-price series are invalid")
        if len({item.provider_asset_id for item in self.series}) != len(self.series):
            raise ValueError("daily closing-price asset IDs must be unique")
        if any(item.provider_id != self.provider_id for item in self.series):
            raise ValueError("daily closing-price series use different providers")
        if any(item.closes[0].day != self.start or item.closes[-1].day != self.end for item in self.series):
            raise ValueError("daily closing-price series range is incomplete")


def ingest_daily_closing_prices(
    batch: CryptoMarketCapBatch, provider: CanonicalPriceDataProvider, start: date, end: date
) -> DailyClosingPriceIngestion:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    if getattr(provider, "provider_id", None) != batch.provider_id:
        raise VNextExternalDataError("daily closing-price provider is incompatible")
    series = tuple(fetch_canonical_daily_closes(provider, asset.provider_asset_id, start, end) for asset in batch.assets)
    return DailyClosingPriceIngestion(batch.provider_id, start, end, series)
