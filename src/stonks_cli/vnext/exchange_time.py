from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class ExchangeTimeZone(StrEnum):
    SINGAPORE = "Asia/Singapore"
    US_EASTERN = "America/New_York"


def normalize_exchange_timestamp(value: object, exchange_time_zone: ExchangeTimeZone) -> datetime:
    if not isinstance(exchange_time_zone, ExchangeTimeZone):
        raise TypeError("exchange time zone is required")
    if not isinstance(value, str):
        raise ValueError("exchange timestamp must be a string")
    naive = _parse_exchange_timestamp(value)
    zone = ZoneInfo(exchange_time_zone.value)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    first_valid = first.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive
    second_valid = second.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == naive
    if not first_valid and not second_valid:
        raise ValueError("exchange timestamp is nonexistent")
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        raise ValueError("exchange timestamp is ambiguous")
    return (first if first_valid else second).astimezone(UTC)


def _parse_exchange_timestamp(value: str) -> datetime:
    for timestamp_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value, timestamp_format)
        except ValueError:
            pass
    raise ValueError("exchange timestamp must use YYYY-MM-DD HH:MM:SS[.ffffff]")
