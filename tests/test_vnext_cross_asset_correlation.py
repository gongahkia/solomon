from datetime import date

import pytest

from stonks_cli.vnext.asset_returns import AssetReturnSeries, DailyAssetReturn
from stonks_cli.vnext.cross_asset_correlation import calculate_cross_asset_correlations


def test_cross_asset_correlation_calculates_ordered_pearson_pairs():
    bitcoin = AssetReturnSeries(
        "fixture", "bitcoin", (DailyAssetReturn(date(2026, 7, 13), 0.01), DailyAssetReturn(date(2026, 7, 14), 0.02))
    )
    ethereum = AssetReturnSeries(
        "fixture", "ethereum", (DailyAssetReturn(date(2026, 7, 13), 0.02), DailyAssetReturn(date(2026, 7, 14), 0.04))
    )

    correlations = calculate_cross_asset_correlations((ethereum, bitcoin))

    assert correlations[0].first_asset_id == "bitcoin"
    assert correlations[0].second_asset_id == "ethereum"
    assert correlations[0].correlation == pytest.approx(1.0)


def test_cross_asset_correlation_fails_closed_for_misaligned_or_zero_variance_series():
    first = AssetReturnSeries(
        "fixture", "bitcoin", (DailyAssetReturn(date(2026, 7, 13), 0.01), DailyAssetReturn(date(2026, 7, 14), 0.02))
    )
    misaligned = AssetReturnSeries(
        "fixture", "ethereum", (DailyAssetReturn(date(2026, 7, 14), 0.01), DailyAssetReturn(date(2026, 7, 15), 0.02))
    )
    flat = AssetReturnSeries(
        "fixture", "ethereum", (DailyAssetReturn(date(2026, 7, 13), 0.01), DailyAssetReturn(date(2026, 7, 14), 0.01))
    )

    with pytest.raises(ValueError, match="not aligned"):
        calculate_cross_asset_correlations((first, misaligned))
    with pytest.raises(ValueError, match="zero-variance"):
        calculate_cross_asset_correlations((first, flat))
