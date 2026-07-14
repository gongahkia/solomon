from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapBatch
from stonks_cli.vnext.foundation import as_utc

_PROVIDER_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class MarketDataProvenance:
    provider_id: str
    source_url: str
    retrieved_at: datetime
    response_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROVIDER_ID_PATTERN.fullmatch(self.provider_id):
            raise ValueError("market-data provenance provider ID is invalid")
        if not isinstance(self.source_url, str):
            raise ValueError("market-data provenance source URL is invalid")
        parsed = urlparse(self.source_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("market-data provenance source URL is invalid")
        if not isinstance(self.response_sha256, str) or not _SHA256_PATTERN.fullmatch(self.response_sha256):
            raise ValueError("market-data provenance response hash is invalid")
        object.__setattr__(self, "retrieved_at", as_utc(self.retrieved_at))


@dataclass(frozen=True)
class ProvenancedCryptoMarketCapBatch:
    batch: CryptoMarketCapBatch
    provenance: MarketDataProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.batch, CryptoMarketCapBatch):
            raise TypeError("provenanced crypto market-cap batch is invalid")
        if not isinstance(self.provenance, MarketDataProvenance):
            raise TypeError("market-data provenance is invalid")
        if self.batch.provider_id != self.provenance.provider_id:
            raise ValueError("market-data provenance provider does not match batch")


def attach_market_data_provenance(
    batch: CryptoMarketCapBatch, provenance: MarketDataProvenance
) -> ProvenancedCryptoMarketCapBatch:
    return ProvenancedCryptoMarketCapBatch(batch, provenance)
