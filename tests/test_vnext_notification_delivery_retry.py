from datetime import UTC, datetime
from uuid import UUID

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import FrozenUTCClock
from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryRecord,
    NotificationDeliveryStatus,
    append_notification_delivery_log,
    load_notification_delivery_log,
)
from stonks_cli.vnext.notification_delivery_retry import retry_failed_notification_delivery
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt


def test_notification_retry_persists_one_delivered_retry_outcome(tmp_path):
    path = tmp_path / "notification-deliveries.json"
    failed = _failed_record()
    append_notification_delivery_log(path, failed)
    calls = []

    outcome = retry_failed_notification_delivery(
        path,
        failed.delivery_id,
        lambda: calls.append("retried") or TelegramMessageReceipt("-100123", 8),
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        retry_delivery_id=UUID("00000000-0000-4000-8000-000000000002"),
    )

    assert calls == ["retried"]
    assert outcome.status is NotificationDeliveryStatus.DELIVERED
    assert outcome.receipt == TelegramMessageReceipt("-100123", 8)
    assert load_notification_delivery_log(path).records == (failed, outcome)


def test_notification_retry_persists_a_failed_outcome_for_unavailable_delivery(tmp_path):
    path = tmp_path / "notification-deliveries.json"
    failed = _failed_record()
    append_notification_delivery_log(path, failed)

    outcome = retry_failed_notification_delivery(
        path,
        failed.delivery_id,
        lambda: _raise_unavailable(),
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        retry_delivery_id=UUID("00000000-0000-4000-8000-000000000002"),
    )

    assert outcome.status is NotificationDeliveryStatus.FAILED
    assert outcome.failure_code == "telegram.delivery_unavailable"
    assert load_notification_delivery_log(path).records == (failed, outcome)


def _failed_record() -> NotificationDeliveryRecord:
    return NotificationDeliveryRecord(
        UUID("00000000-0000-4000-8000-000000000001"),
        "daily-risk",
        "daily_report",
        datetime(2026, 7, 14, 2, tzinfo=UTC),
        NotificationDeliveryStatus.FAILED,
        failure_code="telegram.delivery_unavailable",
    )


def _raise_unavailable() -> TelegramMessageReceipt:
    raise VNextExternalDataError("unavailable")
