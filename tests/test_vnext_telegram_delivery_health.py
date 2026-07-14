from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryLog,
    NotificationDeliveryRecord,
    NotificationDeliveryStatus,
)
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt
from stonks_cli.vnext.telegram_delivery_health import TelegramDeliveryHealthStatus, monitor_telegram_delivery_health

NOW = datetime(2026, 7, 14, 3, tzinfo=UTC)


def test_telegram_delivery_health_reports_recent_failure_fraction():
    log = NotificationDeliveryLog((_record("1", NotificationDeliveryStatus.DELIVERED, NOW), _record("2", NotificationDeliveryStatus.FAILED, NOW)))

    report = monitor_telegram_delivery_health(log, NOW, maximum_age=timedelta(minutes=5), maximum_failure_fraction=0.4)

    assert report.status is TelegramDeliveryHealthStatus.DEGRADED
    assert (report.total_deliveries, report.failed_deliveries) == (2, 1)


@pytest.mark.parametrize("log,maximum_age", [(None, timedelta(minutes=5)), (NotificationDeliveryLog(()), timedelta()), (NotificationDeliveryLog(()), timedelta(minutes=5))])
def test_telegram_delivery_health_fails_closed_for_malformed_or_missing_data(log, maximum_age):
    if log == NotificationDeliveryLog(()) and maximum_age > timedelta():
        assert monitor_telegram_delivery_health(log, NOW, maximum_age=maximum_age, maximum_failure_fraction=0.1).status is TelegramDeliveryHealthStatus.DEGRADED
        return
    with pytest.raises((TypeError, ValueError), match="telegram-delivery health"):
        monitor_telegram_delivery_health(log, NOW, maximum_age=maximum_age, maximum_failure_fraction=0.1)  # type: ignore[arg-type]


def _record(suffix: str, status: NotificationDeliveryStatus, attempted_at: datetime) -> NotificationDeliveryRecord:
    return NotificationDeliveryRecord(
        UUID(f"00000000-0000-4000-8000-00000000000{suffix}"),
        "daily-risk",
        "daily_report",
        attempted_at,
        status,
        TelegramMessageReceipt("-100123", int(suffix)) if status is NotificationDeliveryStatus.DELIVERED else None,
        None if status is NotificationDeliveryStatus.DELIVERED else "telegram.delivery_unavailable",
    )
