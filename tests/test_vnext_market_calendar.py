from datetime import date, time

import pytest

from stonks_cli.vnext.market_calendar import NYSECashEquityCalendar2026, USMarketSessionStatus


def test_nyse_2026_calendar_models_regular_closed_and_early_sessions():
    calendar = NYSECashEquityCalendar2026()

    assert calendar.session_on(date(2026, 1, 2)).status is USMarketSessionStatus.REGULAR
    assert calendar.session_on(date(2026, 1, 2)).closes_at_et == time(16)
    assert calendar.session_on(date(2026, 7, 3)).status is USMarketSessionStatus.CLOSED
    assert calendar.session_on(date(2026, 11, 27)).status is USMarketSessionStatus.EARLY_CLOSE
    assert calendar.session_on(date(2026, 11, 27)).closes_at_et == time(13)


@pytest.mark.parametrize("session_date", [date(2026, 1, 3), date(2025, 12, 31), date(2027, 1, 1)])
def test_nyse_2026_calendar_rejects_out_of_scope_dates_or_closes_weekends(session_date):
    calendar = NYSECashEquityCalendar2026()
    if session_date.year == 2026:
        assert calendar.session_on(session_date).status is USMarketSessionStatus.CLOSED
    else:
        with pytest.raises(ValueError):
            calendar.session_on(session_date)
