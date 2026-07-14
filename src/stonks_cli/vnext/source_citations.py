from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.market_data_provenance import MarketDataProvenance

SOURCE_CITATION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SourceCitation:
    provider_id: str
    source_url: str
    retrieved_at: datetime
    response_sha256: str

    def __post_init__(self) -> None:
        provenance = MarketDataProvenance(self.provider_id, self.source_url, self.retrieved_at, self.response_sha256)
        object.__setattr__(self, "retrieved_at", as_utc(provenance.retrieved_at))

    @classmethod
    def from_provenance(cls, provenance: MarketDataProvenance) -> SourceCitation:
        if not isinstance(provenance, MarketDataProvenance):
            raise TypeError("source citation requires market-data provenance")
        return cls(provenance.provider_id, provenance.source_url, provenance.retrieved_at, provenance.response_sha256)

    def to_data(self) -> dict[str, object]:
        return {
            "version": SOURCE_CITATION_SCHEMA_VERSION,
            "provider_id": self.provider_id,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at.isoformat().replace("+00:00", "Z"),
            "response_sha256": self.response_sha256,
        }

    @classmethod
    def from_data(cls, data: object) -> SourceCitation:
        if not isinstance(data, dict) or set(data) != {"version", "provider_id", "source_url", "retrieved_at", "response_sha256"}:
            raise ValueError("source citation fields are invalid")
        if data["version"] != SOURCE_CITATION_SCHEMA_VERSION or not all(
            isinstance(data[field], str) for field in ("provider_id", "source_url", "retrieved_at", "response_sha256")
        ):
            raise ValueError("source citation fields are invalid")
        try:
            return cls(data["provider_id"], data["source_url"], datetime.fromisoformat(data["retrieved_at"]), data["response_sha256"])
        except (TypeError, ValueError) as error:
            raise ValueError("source citation is malformed") from error
