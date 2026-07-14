from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from stonks_cli.vnext.market_calendar import NYSECashEquityCalendar2026, SGXCashEquityCalendar2026
from stonks_cli.vnext.market_status import MarketStatus, MarketStatusService, MarketVenue


def test_market_status_service_uses_us_and_sg_calendar_sessions():
    service = MarketStatusService(NYSECashEquityCalendar2026(), SGXCashEquityCalendar2026())

    assert service.status_at(MarketVenue.US_EQUITIES, datetime(2026, 1, 2, 10, tzinfo=ZoneInfo("America/New_York"))).status is MarketStatus.OPEN
    assert service.status_at(MarketVenue.US_EQUITIES, datetime(2026, 7, 3, 10, tzinfo=ZoneInfo("America/New_York"))).status is MarketStatus.CLOSED
    assert service.status_at(MarketVenue.SGX, datetime(2026, 1, 2, 12, 30, tzinfo=ZoneInfo("Asia/Singapore"))).status is MarketStatus.MIDDAY_BREAK
    assert service.status_at(MarketVenue.SGX, datetime(2026, 1, 2, 13, tzinfo=ZoneInfo("Asia/Singapore"))).status is MarketStatus.OPEN


def test_market_status_service_rejects_naive_or_out_of_scope_observations():
    service = MarketStatusService(NYSECashEquityCalendar2026(), SGXCashEquityCalendar2026())
    with pytest.raises(ValueError):
        service.status_at(MarketVenue.SGX, datetime(2026, 1, 2, 9))
    with pytest.raises(ValueError):
        service.status_at(MarketVenue.SGX, datetime(2027, 1, 2, 9, tzinfo=ZoneInfo("Asia/Singapore")))
