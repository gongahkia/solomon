from datetime import date

import pytest

from stonks_cli.vnext.mean_reversion_factor import calculate_mean_reversion_factor
from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries


def test_mean_reversion_factor_is_negated_latest_close_z_score_and_flat_windows_are_neutral():
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (
            CanonicalDailyClose(date(2026, 7, 13), 100.0),
            CanonicalDailyClose(date(2026, 7, 14), 110.0),
            CanonicalDailyClose(date(2026, 7, 15), 90.0),
        ),
    )
    flat = CanonicalPriceSeries(
        "fixture",
        "ethereum",
        (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 100.0)),
    )

    assert calculate_mean_reversion_factor(series, 3).z_score == pytest.approx(1.224744871)
    assert calculate_mean_reversion_factor(flat, 2).z_score == 0.0


@pytest.mark.parametrize("window_days", [1, 4, True])
def test_mean_reversion_factor_fails_closed_for_invalid_windows(window_days):
    series = CanonicalPriceSeries(
        "fixture",
        "bitcoin",
        (CanonicalDailyClose(date(2026, 7, 13), 100.0), CanonicalDailyClose(date(2026, 7, 14), 110.0)),
    )

    with pytest.raises(ValueError):
        calculate_mean_reversion_factor(series, window_days)
