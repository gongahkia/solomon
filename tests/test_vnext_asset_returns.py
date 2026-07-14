from datetime import date

import pytest

from stonks_cli.vnext.asset_returns import calculate_asset_returns
from stonks_cli.vnext.daily_closing_prices import DailyClosingPriceIngestion
from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries


def test_asset_returns_calculate_deterministic_close_to_close_fraction():
    ingestion = DailyClosingPriceIngestion(
        "fixture",
        date(2026, 7, 13),
        date(2026, 7, 15),
        (
            CanonicalPriceSeries(
                "fixture",
                "bitcoin",
                (
                    CanonicalDailyClose(date(2026, 7, 13), 100.0),
                    CanonicalDailyClose(date(2026, 7, 14), 110.0),
                    CanonicalDailyClose(date(2026, 7, 15), 99.0),
                ),
            ),
        ),
    )

    returns = calculate_asset_returns(ingestion)

    assert returns[0].provider_asset_id == "bitcoin"
    assert returns[0].returns[0].day == date(2026, 7, 14)
    assert returns[0].returns[0].return_fraction == pytest.approx(0.1)
    assert returns[0].returns[1].return_fraction == pytest.approx(-0.1)


def test_asset_returns_fail_closed_when_series_has_fewer_than_two_prices():
    ingestion = DailyClosingPriceIngestion(
        "fixture",
        date(2026, 7, 13),
        date(2026, 7, 13),
        (CanonicalPriceSeries("fixture", "bitcoin", (CanonicalDailyClose(date(2026, 7, 13), 100.0),)),),
    )

    with pytest.raises(ValueError, match="at least two"):
        calculate_asset_returns(ingestion)
