from datetime import date

import pytest

from stonks_cli.vnext.momentum_factor import calculate_momentum_factor
from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries


def test_momentum_factor_is_cumulative_return_over_explicit_window():
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (
            CanonicalDailyClose(date(2026, 7, 13), 100.0),
            CanonicalDailyClose(date(2026, 7, 14), 110.0),
            CanonicalDailyClose(date(2026, 7, 15), 121.0),
        ),
    )

    assert calculate_momentum_factor(series, 3).return_fraction == pytest.approx(0.21)


@pytest.mark.parametrize("window_days", [1, 4, True])
def test_momentum_factor_fails_closed_for_invalid_windows(window_days):
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 110.0)),
    )

    with pytest.raises(ValueError):
        calculate_momentum_factor(series, window_days)
