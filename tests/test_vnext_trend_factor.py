from datetime import date
from math import log

import pytest

from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries
from stonks_cli.vnext.trend_factor import calculate_trend_factor


def test_trend_factor_is_annualized_ols_log_price_slope_over_explicit_window():
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (
            CanonicalDailyClose(date(2026, 7, 13), 100.0),
            CanonicalDailyClose(date(2026, 7, 14), 110.0),
            CanonicalDailyClose(date(2026, 7, 15), 121.0),
        ),
    )

    result = calculate_trend_factor(series, 3)

    assert result.annualized_log_slope == pytest.approx(log(1.1) * 365)


@pytest.mark.parametrize("window_days", [1, 4, True])
def test_trend_factor_fails_closed_for_invalid_windows(window_days):
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 110.0)),
    )

    with pytest.raises(ValueError):
        calculate_trend_factor(series, window_days)
