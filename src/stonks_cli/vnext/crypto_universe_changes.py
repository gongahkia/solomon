from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset
from stonks_cli.vnext.crypto_universe_snapshot import CryptoUniverseSnapshot
from stonks_cli.vnext.errors import VNextInvariantError


@dataclass(frozen=True)
class CryptoUniverseRankChange:
    provider_asset_id: str
    previous_rank: int
    current_rank: int

    def __post_init__(self) -> None:
        if not isinstance(self.provider_asset_id, str) or not self.provider_asset_id:
            raise ValueError("crypto universe rank-change asset ID is invalid")
        if not all(isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 for rank in (self.previous_rank, self.current_rank)):
            raise ValueError("crypto universe ranks are invalid")
        if self.previous_rank == self.current_rank:
            raise ValueError("crypto universe rank change must differ")


@dataclass(frozen=True)
class CryptoUniverseChanges:
    previous_snapshot_id: UUID
    current_snapshot_id: UUID
    added: tuple[CryptoMarketCapAsset, ...]
    removed: tuple[CryptoMarketCapAsset, ...]
    rank_changes: tuple[CryptoUniverseRankChange, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.previous_snapshot_id, UUID) or not isinstance(self.current_snapshot_id, UUID):
            raise TypeError("crypto universe snapshot IDs are invalid")
        if self.previous_snapshot_id == self.current_snapshot_id:
            raise ValueError("crypto universe snapshots must differ")
        if not all(isinstance(asset, CryptoMarketCapAsset) for asset in self.added + self.removed):
            raise TypeError("crypto universe changed assets are invalid")
        if not all(isinstance(change, CryptoUniverseRankChange) for change in self.rank_changes):
            raise TypeError("crypto universe rank changes are invalid")


def detect_crypto_universe_changes(
    previous: CryptoUniverseSnapshot, current: CryptoUniverseSnapshot
) -> CryptoUniverseChanges:
    if not isinstance(previous, CryptoUniverseSnapshot) or not isinstance(current, CryptoUniverseSnapshot):
        raise TypeError("crypto universe snapshots are required")
    if current.captured_at <= previous.captured_at:
        raise VNextInvariantError("crypto universe snapshots must be chronological")
    if current.batch.provider_id != previous.batch.provider_id:
        raise VNextInvariantError("crypto universe snapshots use different providers")
    previous_assets = {asset.provider_asset_id: asset for asset in previous.batch.assets}
    current_assets = {asset.provider_asset_id: asset for asset in current.batch.assets}
    added = tuple(asset for asset in current.batch.assets if asset.provider_asset_id not in previous_assets)
    removed = tuple(asset for asset in previous.batch.assets if asset.provider_asset_id not in current_assets)
    rank_changes = tuple(
        CryptoUniverseRankChange(asset_id, previous_assets[asset_id].market_cap_rank, current_assets[asset_id].market_cap_rank)
        for asset_id in current_assets
        if asset_id in previous_assets and previous_assets[asset_id].market_cap_rank != current_assets[asset_id].market_cap_rank
    )
    return CryptoUniverseChanges(previous.snapshot_id, current.snapshot_id, added, removed, rank_changes)
