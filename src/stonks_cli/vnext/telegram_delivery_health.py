from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.notification_delivery_log import NotificationDeliveryLog, NotificationDeliveryStatus


class TelegramDeliveryHealthStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class TelegramDeliveryHealth:
    evaluated_at: datetime
    total_deliveries: int
    failed_deliveries: int
    maximum_failure_fraction: float
    status: TelegramDeliveryHealthStatus
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (self.total_deliveries, self.failed_deliveries)) or self.failed_deliveries > self.total_deliveries:
            raise ValueError("telegram-delivery health counts are invalid")
        if not isinstance(self.maximum_failure_fraction, float) or not math.isfinite(self.maximum_failure_fraction) or not 0 <= self.maximum_failure_fraction <= 1:
            raise ValueError("telegram-delivery health threshold is invalid")
        if not isinstance(self.status, TelegramDeliveryHealthStatus) or not isinstance(self.reason, str) or not self.reason:
            raise ValueError("telegram-delivery health status is invalid")


def monitor_telegram_delivery_health(
    log: NotificationDeliveryLog,
    evaluated_at: datetime,
    *,
    maximum_age: timedelta,
    maximum_failure_fraction: float,
) -> TelegramDeliveryHealth:
    if not isinstance(log, NotificationDeliveryLog):
        raise TypeError("telegram-delivery health requires notification delivery log")
    evaluation_time = as_utc(evaluated_at)
    if not isinstance(maximum_age, timedelta) or maximum_age <= timedelta():
        raise ValueError("telegram-delivery health maximum age is invalid")
    if not isinstance(maximum_failure_fraction, float) or not math.isfinite(maximum_failure_fraction) or not 0 <= maximum_failure_fraction <= 1:
        raise ValueError("telegram-delivery health maximum failure fraction is invalid")
    if any(record.attempted_at > evaluation_time for record in log.records):
        raise ValueError("telegram-delivery health cannot evaluate future deliveries")
    recent = tuple(record for record in log.records if evaluation_time - record.attempted_at <= maximum_age)
    if not recent:
        return TelegramDeliveryHealth(evaluation_time, 0, 0, maximum_failure_fraction, TelegramDeliveryHealthStatus.DEGRADED, "no_recent_deliveries")
    failed = sum(record.status is NotificationDeliveryStatus.FAILED for record in recent)
    status = TelegramDeliveryHealthStatus.HEALTHY if failed / len(recent) <= maximum_failure_fraction else TelegramDeliveryHealthStatus.DEGRADED
    return TelegramDeliveryHealth(evaluation_time, len(recent), failed, maximum_failure_fraction, status, "failure_fraction_within_limit" if status is TelegramDeliveryHealthStatus.HEALTHY else "failure_fraction_exceeded")
