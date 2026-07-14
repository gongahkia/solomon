from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum


class USMarketSessionStatus(StrEnum):
    CLOSED = "closed"
    EARLY_CLOSE = "early_close"
    REGULAR = "regular"


@dataclass(frozen=True)
class USMarketSession:
    session_date: date
    status: USMarketSessionStatus
    opens_at_et: time | None
    closes_at_et: time | None

    def __post_init__(self) -> None:
        if not isinstance(self.session_date, date):
            raise TypeError("US market session date is required")
        if not isinstance(self.status, USMarketSessionStatus):
            raise TypeError("US market session status is required")
        if self.status is USMarketSessionStatus.CLOSED:
            if self.opens_at_et is not None or self.closes_at_et is not None:
                raise ValueError("closed US market sessions have no trading hours")
        elif self.opens_at_et != time(9, 30) or self.closes_at_et not in {time(13), time(16)}:
            raise ValueError("US market session hours are invalid")


class NYSECashEquityCalendar2026:
    _closed_dates = frozenset(
        {
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
        }
    )
    _early_close_dates = frozenset({date(2026, 11, 27), date(2026, 12, 24)})

    def session_on(self, session_date: date) -> USMarketSession:
        if not isinstance(session_date, date) or session_date.year != 2026:
            raise ValueError("NYSE 2026 calendar only accepts dates in 2026")
        if session_date.weekday() >= 5 or session_date in self._closed_dates:
            return USMarketSession(session_date, USMarketSessionStatus.CLOSED, None, None)
        if session_date in self._early_close_dates:
            return USMarketSession(session_date, USMarketSessionStatus.EARLY_CLOSE, time(9, 30), time(13))
        return USMarketSession(session_date, USMarketSessionStatus.REGULAR, time(9, 30), time(16))


class SGMarketSessionStatus(StrEnum):
    CLOSED = "closed"
    REGULAR = "regular"


@dataclass(frozen=True)
class SGMarketSession:
    session_date: date
    status: SGMarketSessionStatus
    morning_opens_at_sgt: time | None
    morning_closes_at_sgt: time | None
    afternoon_opens_at_sgt: time | None
    afternoon_closes_at_sgt: time | None

    def __post_init__(self) -> None:
        if not isinstance(self.session_date, date) or not isinstance(self.status, SGMarketSessionStatus):
            raise TypeError("SG market session fields are required")
        session_times = (self.morning_opens_at_sgt, self.morning_closes_at_sgt, self.afternoon_opens_at_sgt, self.afternoon_closes_at_sgt)
        if self.status is SGMarketSessionStatus.CLOSED:
            if any(session_times):
                raise ValueError("closed SG market sessions have no trading hours")
        elif session_times != (time(9), time(12), time(13), time(17)):
            raise ValueError("SG market session hours are invalid")


class SGXCashEquityCalendar2026:
    _closed_dates = frozenset(
        {
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
        }
    )

    def session_on(self, session_date: date) -> SGMarketSession:
        if not isinstance(session_date, date) or session_date.year != 2026:
            raise ValueError("SGX 2026 calendar only accepts dates in 2026")
        if session_date.weekday() >= 5 or session_date in self._closed_dates:
            return SGMarketSession(session_date, SGMarketSessionStatus.CLOSED, None, None, None, None)
        return SGMarketSession(session_date, SGMarketSessionStatus.REGULAR, time(9), time(12), time(13), time(17))
