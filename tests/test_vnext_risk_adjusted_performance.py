from datetime import date

import pytest

from stonks_cli.vnext.asset_returns import AssetReturnSeries, DailyAssetReturn
from stonks_cli.vnext.risk_adjusted_performance import calculate_risk_adjusted_performance


def test_risk_adjusted_performance_calculates_annualized_mean_volatility_and_sharpe():
    series = AssetReturnSeries(
        "fixture",
        "bitcoin",
        (DailyAssetReturn(date(2026, 7, 13), 0.01), DailyAssetReturn(date(2026, 7, 14), 0.02)),
    )

    result = calculate_risk_adjusted_performance(series)

    assert result.annualized_mean_return == pytest.approx(0.015 * 365)
    assert result.annualized_volatility == pytest.approx((0.00005 * 365) ** 0.5)
    assert result.sharpe_ratio == pytest.approx(result.annualized_mean_return / result.annualized_volatility)


def test_risk_adjusted_performance_handles_neutral_flat_returns_and_rejects_undefined_sharpe():
    neutral = AssetReturnSeries(
        "fixture",
        "bitcoin",
        (DailyAssetReturn(date(2026, 7, 13), 0.0), DailyAssetReturn(date(2026, 7, 14), 0.0)),
    )
    non_neutral = AssetReturnSeries(
        "fixture",
        "ethereum",
        (DailyAssetReturn(date(2026, 7, 13), 0.01), DailyAssetReturn(date(2026, 7, 14), 0.01)),
    )

    assert calculate_risk_adjusted_performance(neutral).sharpe_ratio == 0.0
    with pytest.raises(ValueError, match="undefined"):
        calculate_risk_adjusted_performance(non_neutral)
