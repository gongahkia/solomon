from datetime import date

import pytest

from stonks_cli.vnext.asset_returns import AssetReturnSeries, DailyAssetReturn
from stonks_cli.vnext.realized_volatility import calculate_realized_volatility


def test_realized_volatility_uses_annualized_sample_standard_deviation():
    series = AssetReturnSeries(
        "fixture",
        "bitcoin",
        (DailyAssetReturn(date(2026, 7, 13), 0.1), DailyAssetReturn(date(2026, 7, 14), -0.1)),
    )

    result = calculate_realized_volatility(series)

    assert result.daily_observations == 2
    assert result.annualized_volatility == pytest.approx((0.02 * 365) ** 0.5)


def test_realized_volatility_fails_closed_for_insufficient_returns():
    series = AssetReturnSeries("fixture", "bitcoin", (DailyAssetReturn(date(2026, 7, 13), 0.1),))

    with pytest.raises(ValueError, match="at least two"):
        calculate_realized_volatility(series)
