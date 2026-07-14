from __future__ import annotations

import math

from stonks_cli.vnext.crypto_market_cap import CryptoMarketCapAsset, CryptoMarketCapBatch


def filter_crypto_universe_by_liquidity(
    batch: CryptoMarketCapBatch, minimum_liquidity_usd: float
) -> tuple[CryptoMarketCapAsset, ...]:
    if not isinstance(batch, CryptoMarketCapBatch):
        raise TypeError("crypto market-cap batch is required")
    if (
        not isinstance(minimum_liquidity_usd, float)
        or not math.isfinite(minimum_liquidity_usd)
        or minimum_liquidity_usd < 0
    ):
        raise ValueError("crypto liquidity threshold must be a non-negative finite USD value")
    return tuple(asset for asset in batch.assets if asset.total_volume_usd >= minimum_liquidity_usd)
