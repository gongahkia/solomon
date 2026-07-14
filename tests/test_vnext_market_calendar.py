from datetime import date, time

import pytest

from stonks_cli.vnext.market_calendar import (
    NYSECashEquityCalendar2026,
    SGMarketSessionStatus,
    SGXCashEquityCalendar2026,
    USMarketSessionStatus,
)


def test_nyse_2026_calendar_models_regular_closed_and_early_sessions():
    calendar = NYSECashEquityCalendar2026()

    assert calendar.session_on(date(2026, 1, 2)).status is USMarketSessionStatus.REGULAR
    assert calendar.session_on(date(2026, 1, 2)).closes_at_et == time(16)
    assert calendar.session_on(date(2026, 7, 3)).status is USMarketSessionStatus.CLOSED
    assert calendar.session_on(date(2026, 11, 27)).status is USMarketSessionStatus.EARLY_CLOSE
    assert calendar.session_on(date(2026, 11, 27)).closes_at_et == time(13)


@pytest.mark.parametrize(
    "session_date",
    [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ],
)
def test_nyse_2026_calendar_closes_on_every_encoded_exchange_holiday(session_date):
    assert NYSECashEquityCalendar2026().session_on(session_date).status is USMarketSessionStatus.CLOSED


@pytest.mark.parametrize("session_date", [date(2026, 1, 3), date(2025, 12, 31), date(2027, 1, 1)])
def test_nyse_2026_calendar_rejects_out_of_scope_dates_or_closes_weekends(session_date):
    calendar = NYSECashEquityCalendar2026()
    if session_date.year == 2026:
        assert calendar.session_on(session_date).status is USMarketSessionStatus.CLOSED
    else:
        with pytest.raises(ValueError):
            calendar.session_on(session_date)


def test_sgx_2026_calendar_models_official_closures_and_split_regular_session():
    calendar = SGXCashEquityCalendar2026()

    regular = calendar.session_on(date(2026, 1, 2))
    assert regular.status is SGMarketSessionStatus.REGULAR
    assert (regular.morning_opens_at_sgt, regular.morning_closes_at_sgt, regular.afternoon_opens_at_sgt, regular.afternoon_closes_at_sgt) == (time(9), time(12), time(13), time(17))
    assert calendar.session_on(date(2026, 2, 17)).status is SGMarketSessionStatus.CLOSED
    assert calendar.session_on(date(2026, 6, 1)).status is SGMarketSessionStatus.CLOSED


@pytest.mark.parametrize(
    "session_date",
    [
        date(2026, 1, 1),
        date(2026, 2, 17),
        date(2026, 2, 18),
        date(2026, 4, 3),
        date(2026, 5, 1),
        date(2026, 5, 27),
        date(2026, 6, 1),
        date(2026, 8, 10),
        date(2026, 11, 9),
        date(2026, 12, 25),
    ],
)
def test_sgx_2026_calendar_closes_on_every_encoded_exchange_holiday(session_date):
    assert SGXCashEquityCalendar2026().session_on(session_date).status is SGMarketSessionStatus.CLOSED


@pytest.mark.parametrize("calendar", [NYSECashEquityCalendar2026(), SGXCashEquityCalendar2026()])
@pytest.mark.parametrize("session_date", [date(2027, 1, 1), "2026-01-02"])
def test_2026_market_calendars_reject_out_of_scope_or_malformed_dates(calendar, session_date):
    with pytest.raises(ValueError):
        calendar.session_on(session_date)
