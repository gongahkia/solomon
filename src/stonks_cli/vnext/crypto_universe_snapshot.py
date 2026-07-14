from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch
from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory
from stonks_cli.vnext.foundation import Clock, as_utc

CRYPTO_UNIVERSE_SNAPSHOT_VERSION = 1


@dataclass(frozen=True)
class CryptoUniverseSnapshot:
    snapshot_id: UUID
    captured_at: datetime
    batch: CryptoMarketCapBatch

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise TypeError("crypto universe snapshot ID must be a UUID")
        if not isinstance(self.batch, CryptoMarketCapBatch):
            raise TypeError("crypto universe snapshot batch is required")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))

    def to_data(self) -> dict[str, object]:
        return {
            "version": CRYPTO_UNIVERSE_SNAPSHOT_VERSION,
            "snapshot_id": str(self.snapshot_id),
            "captured_at": _format_timestamp(self.captured_at),
            "provider_id": self.batch.provider_id,
            "assets": [
                {
                    "provider_asset_id": asset.provider_asset_id,
                    "symbol": asset.symbol,
                    "name": asset.name,
                    "market_cap_usd": asset.market_cap_usd,
                    "total_volume_usd": asset.total_volume_usd,
                    "market_cap_rank": asset.market_cap_rank,
                    "reported_at": _format_timestamp(asset.reported_at),
                }
                for asset in self.batch.assets
            ],
        }

    @classmethod
    def from_data(cls, data: object) -> CryptoUniverseSnapshot:
        if not isinstance(data, dict) or set(data) != {"version", "snapshot_id", "captured_at", "provider_id", "assets"}:
            raise ValueError("crypto universe snapshot fields are invalid")
        if data["version"] != CRYPTO_UNIVERSE_SNAPSHOT_VERSION:
            raise ValueError("crypto universe snapshot version is unsupported")
        if not isinstance(data["snapshot_id"], str) or not isinstance(data["captured_at"], str) or not isinstance(data["provider_id"], str):
            raise ValueError("crypto universe snapshot fields are invalid")
        if not isinstance(data["assets"], list):
            raise ValueError("crypto universe snapshot assets are invalid")
        try:
            assets = tuple(_asset_from_data(asset) for asset in data["assets"])
            return cls(
                UUID(data["snapshot_id"]),
                datetime.fromisoformat(data["captured_at"]),
                CryptoMarketCapBatch(data["provider_id"], assets),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("crypto universe snapshot is malformed") from error


def create_crypto_universe_snapshot(batch: CryptoMarketCapBatch, clock: Clock, *, snapshot_id: UUID | None = None) -> CryptoUniverseSnapshot:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    if not hasattr(clock, "now") or not callable(clock.now):
        raise TypeError("crypto universe snapshot clock is required")
    return CryptoUniverseSnapshot(snapshot_id or uuid4(), clock.now(), batch)


def save_crypto_universe_snapshot(directory: Path, snapshot: CryptoUniverseSnapshot) -> Path:
    if not isinstance(directory, Path) or not directory.is_absolute():
        raise ValueError("crypto universe snapshot directory must be absolute")
    if not isinstance(snapshot, CryptoUniverseSnapshot):
        raise TypeError("crypto universe snapshot is required")
    ensure_private_directory(directory)
    path = directory / f"crypto-universe-{snapshot.snapshot_id}.json"
    temporary = directory / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(snapshot.to_data(), output, allow_nan=False, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, path)
        os.unlink(temporary)
        _sync_directory(directory)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    enforce_private_file(path)
    return path


def load_crypto_universe_snapshot(path: Path) -> CryptoUniverseSnapshot:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("crypto universe snapshot path must be absolute")
    enforce_private_file(path)
    try:
        return CryptoUniverseSnapshot.from_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("crypto universe snapshot cannot be loaded") from error


def _asset_from_data(data: object) -> CryptoMarketCapAsset:
    if not isinstance(data, dict) or set(data) != {
        "provider_asset_id",
        "symbol",
        "name",
        "market_cap_usd",
        "total_volume_usd",
        "market_cap_rank",
        "reported_at",
    }:
        raise ValueError("crypto universe snapshot asset fields are invalid")
    if not all(isinstance(data[field], str) for field in ("provider_asset_id", "symbol", "name", "reported_at")):
        raise ValueError("crypto universe snapshot asset fields are invalid")
    return CryptoMarketCapAsset(
        data["provider_asset_id"],
        data["symbol"],
        data["name"],
        data["market_cap_usd"],
        data["total_volume_usd"],
        data["market_cap_rank"],
        datetime.fromisoformat(data["reported_at"]),
    )


def _format_timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
