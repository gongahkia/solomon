from datetime import UTC, datetime
from uuid import UUID

import pytest

from stonks_cli.vnext.foundation import FrozenUTCClock
from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryRecord,
    NotificationDeliveryStatus,
    append_notification_delivery_log,
)
from stonks_cli.vnext.operator_acknowledgements import (
    OperatorAcknowledgement,
    OperatorAcknowledgementLog,
    load_operator_acknowledgement_log,
    record_operator_acknowledgement,
)
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt


def test_operator_acknowledgement_persists_once_for_a_delivered_notification(tmp_path):
    delivery_path = tmp_path / "notification-deliveries.json"
    acknowledgement_path = tmp_path / "operator-acknowledgements.json"
    delivered = _delivery(NotificationDeliveryStatus.DELIVERED)
    append_notification_delivery_log(delivery_path, delivered)

    acknowledgement = record_operator_acknowledgement(
        acknowledgement_path,
        delivery_path,
        delivered.delivery_id,
        "operator@example.test",
        FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        acknowledgement_id=UUID("00000000-0000-4000-8000-000000000002"),
    )

    assert acknowledgement.delivery_id == delivered.delivery_id
    assert acknowledgement.operator_id == "operator@example.test"
    assert load_operator_acknowledgement_log(acknowledgement_path) == OperatorAcknowledgementLog((acknowledgement,))
    assert acknowledgement_path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="already acknowledged"):
        record_operator_acknowledgement(
            acknowledgement_path,
            delivery_path,
            delivered.delivery_id,
            "operator@example.test",
            FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC)),
        )


def test_operator_acknowledgement_fails_closed_for_failed_delivery(tmp_path):
    delivery_path = tmp_path / "notification-deliveries.json"
    acknowledgement_path = tmp_path / "operator-acknowledgements.json"
    failed = _delivery(NotificationDeliveryStatus.FAILED)
    append_notification_delivery_log(delivery_path, failed)
    clock = FrozenUTCClock(datetime(2026, 7, 14, 2, 1, tzinfo=UTC))

    with pytest.raises(ValueError, match="not delivered"):
        record_operator_acknowledgement(acknowledgement_path, delivery_path, failed.delivery_id, "operator@example.test", clock)


@pytest.mark.parametrize(
    "data",
    [
        None,
        {},
        {"acknowledgement_id": "not-a-uuid", "delivery_id": "00000000-0000-4000-8000-000000000001", "operator_id": "operator@example.test", "acknowledged_at": "2026-07-14T02:01:00Z"},
        {"acknowledgement_id": "00000000-0000-4000-8000-000000000002", "delivery_id": "00000000-0000-4000-8000-000000000001", "operator_id": "operator id", "acknowledged_at": "2026-07-14T02:01:00Z"},
    ],
)
def test_operator_approval_provenance_rejects_missing_or_malformed_external_data(data):
    with pytest.raises(ValueError, match="operator acknowledgement"):
        OperatorAcknowledgement.from_data(data)


def _delivery(status: NotificationDeliveryStatus) -> NotificationDeliveryRecord:
    return NotificationDeliveryRecord(
        UUID("00000000-0000-4000-8000-000000000001"),
        "daily-risk",
        "daily_report",
        datetime(2026, 7, 14, 2, tzinfo=UTC),
        status,
        TelegramMessageReceipt("-100123", 7) if status is NotificationDeliveryStatus.DELIVERED else None,
        None if status is NotificationDeliveryStatus.DELIVERED else "telegram.delivery_unavailable",
    )
