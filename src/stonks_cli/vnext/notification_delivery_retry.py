from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from stonks_cli.vnext.errors import VNextExternalDataError
from stonks_cli.vnext.foundation import Clock, as_utc
from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryRecord,
    NotificationDeliveryStatus,
    append_notification_delivery_log,
    load_notification_delivery_log,
)
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt


def retry_failed_notification_delivery(
    path: Path,
    failed_delivery_id: UUID,
    retry: Callable[[], TelegramMessageReceipt],
    clock: Clock,
    *,
    retry_delivery_id: UUID | None = None,
) -> NotificationDeliveryRecord:
    if not isinstance(failed_delivery_id, UUID):
        raise TypeError("failed notification delivery ID must be a UUID")
    if not callable(retry):
        raise TypeError("notification retry callback is invalid")
    if not hasattr(clock, "now") or not callable(clock.now):
        raise TypeError("notification retry clock is invalid")
    log = load_notification_delivery_log(path)
    failed = next((record for record in log.records if record.delivery_id == failed_delivery_id), None)
    if failed is None:
        raise ValueError("failed notification delivery is not logged")
    if failed.status is not NotificationDeliveryStatus.FAILED:
        raise ValueError("notification delivery is not failed")
    delivery_id = retry_delivery_id or uuid4()
    if not isinstance(delivery_id, UUID):
        raise TypeError("notification retry delivery ID must be a UUID")
    if any(record.delivery_id == delivery_id for record in log.records):
        raise ValueError("notification retry delivery ID already exists")
    attempted_at = as_utc(clock.now())
    if log.records and attempted_at < log.records[-1].attempted_at:
        raise ValueError("notification retry timestamp precedes delivery log")
    try:
        receipt = retry()
    except VNextExternalDataError:
        outcome = NotificationDeliveryRecord(
            delivery_id,
            failed.subscription_id,
            failed.event_type,
            attempted_at,
            NotificationDeliveryStatus.FAILED,
            failure_code="telegram.delivery_unavailable",
        )
    else:
        outcome = (
            NotificationDeliveryRecord(
                delivery_id,
                failed.subscription_id,
                failed.event_type,
                attempted_at,
                NotificationDeliveryStatus.DELIVERED,
                receipt,
            )
            if isinstance(receipt, TelegramMessageReceipt)
            else NotificationDeliveryRecord(
                delivery_id,
                failed.subscription_id,
                failed.event_type,
                attempted_at,
                NotificationDeliveryStatus.FAILED,
                failure_code="telegram.response_malformed",
            )
        )
    append_notification_delivery_log(path, outcome)
    return outcome
