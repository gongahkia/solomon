from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from stonks_cli.vnext.market_calendar import (
    NYSECashEquityCalendar2026,
    SGMarketSessionStatus,
    SGXCashEquityCalendar2026,
    USMarketSessionStatus,
)


class MarketVenue(StrEnum):
    SGX = "sgx"
    US_EQUITIES = "us_equities"


class MarketStatus(StrEnum):
    CLOSED = "closed"
    MIDDAY_BREAK = "midday_break"
    OPEN = "open"


@dataclass(frozen=True)
class MarketStatusReport:
    venue: MarketVenue
    status: MarketStatus
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.venue, MarketVenue) or not isinstance(self.status, MarketStatus):
            raise TypeError("market status fields are required")
        if not isinstance(self.observed_at, datetime) or self.observed_at.tzinfo is None:
            raise ValueError("market status observation must be timezone-aware")


@dataclass(frozen=True)
class MarketStatusService:
    us_calendar: NYSECashEquityCalendar2026
    sg_calendar: SGXCashEquityCalendar2026

    def status_at(self, venue: MarketVenue, observed_at: datetime) -> MarketStatusReport:
        if not isinstance(venue, MarketVenue):
            raise TypeError("market venue is required")
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError("market status observation must be timezone-aware")
        if venue is MarketVenue.US_EQUITIES:
            local = observed_at.astimezone(ZoneInfo("America/New_York"))
            session = self.us_calendar.session_on(local.date())
            status = MarketStatus.CLOSED
            if session.status is not USMarketSessionStatus.CLOSED and session.opens_at_et <= local.timetz().replace(tzinfo=None) < session.closes_at_et:
                status = MarketStatus.OPEN
        else:
            local = observed_at.astimezone(ZoneInfo("Asia/Singapore"))
            session = self.sg_calendar.session_on(local.date())
            local_time = local.timetz().replace(tzinfo=None)
            if session.status is SGMarketSessionStatus.CLOSED:
                status = MarketStatus.CLOSED
            elif session.morning_opens_at_sgt <= local_time < session.morning_closes_at_sgt or session.afternoon_opens_at_sgt <= local_time < session.afternoon_closes_at_sgt:
                status = MarketStatus.OPEN
            elif session.morning_closes_at_sgt <= local_time < session.afternoon_opens_at_sgt:
                status = MarketStatus.MIDDAY_BREAK
            else:
                status = MarketStatus.CLOSED
        return MarketStatusReport(venue, status, observed_at)
