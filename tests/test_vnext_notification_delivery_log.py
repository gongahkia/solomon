from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryLog,
    NotificationDeliveryRecord,
    NotificationDeliveryStatus,
    append_notification_delivery_log,
    load_notification_delivery_log,
)
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt


def test_notification_delivery_log_persists_private_delivered_and_failed_records(tmp_path):
    path = tmp_path / "notification-deliveries.json"
    delivered = NotificationDeliveryRecord(
        UUID("00000000-0000-4000-8000-000000000001"),
        "daily-risk",
        "daily_report",
        datetime(2026, 7, 14, 2, 0, tzinfo=UTC),
        NotificationDeliveryStatus.DELIVERED,
        TelegramMessageReceipt("-100123", 7),
    )
    failed = NotificationDeliveryRecord(
        UUID("00000000-0000-4000-8000-000000000002"),
        "daily-risk",
        "daily_report",
        datetime(2026, 7, 14, 2, 1, tzinfo=UTC),
        NotificationDeliveryStatus.FAILED,
        failure_code="telegram.response_malformed",
    )

    assert append_notification_delivery_log(path, delivered) == NotificationDeliveryLog((delivered,))
    assert append_notification_delivery_log(path, failed) == NotificationDeliveryLog((delivered, failed))
    assert load_notification_delivery_log(path) == NotificationDeliveryLog((delivered, failed))
    assert path.stat().st_mode & 0o777 == 0o600


def test_notification_delivery_log_fails_closed_for_invalid_records_or_history(tmp_path):
    with pytest.raises(ValueError, match="delivered"):
        NotificationDeliveryRecord(
            UUID("00000000-0000-4000-8000-000000000001"),
            "daily-risk",
            "daily_report",
            datetime(2026, 7, 14, 2, tzinfo=UTC),
            NotificationDeliveryStatus.DELIVERED,
        )
    path = tmp_path / "notification-deliveries.json"
    path.write_text('{"records":[{}],"version":1}', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="cannot be loaded"):
        load_notification_delivery_log(path)
