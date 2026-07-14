from datetime import date

import pytest

from stonks_cli.vnext.daily_closing_prices import DailyClosingPriceIngestion
from stonks_cli.vnext.price_data import CanonicalDailyClose, CanonicalPriceSeries
from stonks_cli.vnext.rolling_drawdown import calculate_rolling_drawdown


def test_rolling_drawdown_uses_running_peak_and_preserves_daily_order():
    ingestion = DailyClosingPriceIngestion(
        "fixture",
        date(2026, 7, 13),
        date(2026, 7, 16),
        (
            CanonicalPriceSeries(
                "fixture",
                "bitcoin",
                (
                    CanonicalDailyClose(date(2026, 7, 13), 100.0),
                    CanonicalDailyClose(date(2026, 7, 14), 120.0),
                    CanonicalDailyClose(date(2026, 7, 15), 90.0),
                    CanonicalDailyClose(date(2026, 7, 16), 110.0),
                ),
            ),
        ),
    )

    values = calculate_rolling_drawdown(ingestion)[0].drawdowns

    assert [item.day for item in values] == [date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16)]
    assert [item.drawdown_fraction for item in values] == pytest.approx([0.0, 0.0, -0.25, -1.0 / 12.0])


def test_rolling_drawdown_rejects_non_ingestion_input():
    with pytest.raises(TypeError):
        calculate_rolling_drawdown("not-an-ingestion")
