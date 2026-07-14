from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory
from stonks_cli.vnext.foundation import as_utc
from stonks_cli.vnext.telegram_client import TelegramMessageReceipt

NOTIFICATION_DELIVERY_LOG_VERSION = 1
_EVENT_TYPE_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_FAILURE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")


class NotificationDeliveryStatus(StrEnum):
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(frozen=True)
class NotificationDeliveryRecord:
    delivery_id: UUID
    subscription_id: str
    event_type: str
    attempted_at: datetime
    status: NotificationDeliveryStatus
    receipt: TelegramMessageReceipt | None = None
    failure_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.delivery_id, UUID):
            raise TypeError("notification delivery ID must be a UUID")
        if not isinstance(self.subscription_id, str) or not self.subscription_id:
            raise ValueError("notification delivery subscription ID is invalid")
        if not isinstance(self.event_type, str) or not _EVENT_TYPE_PATTERN.fullmatch(self.event_type):
            raise ValueError("notification delivery event type is invalid")
        if not isinstance(self.status, NotificationDeliveryStatus):
            raise TypeError("notification delivery status is invalid")
        if self.status is NotificationDeliveryStatus.DELIVERED:
            if not isinstance(self.receipt, TelegramMessageReceipt) or self.failure_code is not None:
                raise ValueError("delivered notification record is invalid")
        elif self.receipt is not None or not isinstance(self.failure_code, str) or not _FAILURE_CODE_PATTERN.fullmatch(self.failure_code):
            raise ValueError("failed notification record is invalid")
        object.__setattr__(self, "attempted_at", as_utc(self.attempted_at))

    def to_data(self) -> dict[str, object]:
        return {
            "delivery_id": str(self.delivery_id),
            "subscription_id": self.subscription_id,
            "event_type": self.event_type,
            "attempted_at": self.attempted_at.isoformat().replace("+00:00", "Z"),
            "status": self.status.value,
            "chat_id": None if self.receipt is None else self.receipt.chat_id,
            "message_id": None if self.receipt is None else self.receipt.message_id,
            "failure_code": self.failure_code,
        }

    @classmethod
    def from_data(cls, data: object) -> NotificationDeliveryRecord:
        if not isinstance(data, dict) or set(data) != {
            "delivery_id",
            "subscription_id",
            "event_type",
            "attempted_at",
            "status",
            "chat_id",
            "message_id",
            "failure_code",
        }:
            raise ValueError("notification delivery record fields are invalid")
        if not all(isinstance(data[field], str) for field in ("delivery_id", "subscription_id", "event_type", "attempted_at", "status")):
            raise ValueError("notification delivery record fields are invalid")
        chat_id = data["chat_id"]
        message_id = data["message_id"]
        failure_code = data["failure_code"]
        if (chat_id is None) != (message_id is None) or not (failure_code is None or isinstance(failure_code, str)):
            raise ValueError("notification delivery record fields are invalid")
        try:
            receipt = None if chat_id is None else TelegramMessageReceipt(chat_id, message_id)
            return cls(
                UUID(data["delivery_id"]),
                data["subscription_id"],
                data["event_type"],
                datetime.fromisoformat(data["attempted_at"]),
                NotificationDeliveryStatus(data["status"]),
                receipt,
                failure_code,
            )
        except (TypeError, ValueError) as error:
            raise ValueError("notification delivery record is malformed") from error


@dataclass(frozen=True)
class NotificationDeliveryLog:
    records: tuple[NotificationDeliveryRecord, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.records, tuple) or not all(isinstance(record, NotificationDeliveryRecord) for record in self.records):
            raise ValueError("notification delivery log records are invalid")
        if len({record.delivery_id for record in self.records}) != len(self.records):
            raise ValueError("notification delivery log IDs must be unique")
        timestamps = tuple(record.attempted_at for record in self.records)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("notification delivery log records must be chronological")

    def to_data(self) -> dict[str, object]:
        return {"version": NOTIFICATION_DELIVERY_LOG_VERSION, "records": [record.to_data() for record in self.records]}

    @classmethod
    def from_data(cls, data: object) -> NotificationDeliveryLog:
        if not isinstance(data, dict) or set(data) != {"version", "records"} or data["version"] != NOTIFICATION_DELIVERY_LOG_VERSION:
            raise ValueError("notification delivery log fields are invalid")
        if not isinstance(data["records"], list):
            raise ValueError("notification delivery log records are invalid")
        try:
            return cls(tuple(NotificationDeliveryRecord.from_data(record) for record in data["records"]))
        except (TypeError, ValueError) as error:
            raise ValueError("notification delivery log is malformed") from error


def append_notification_delivery_log(path: Path, record: NotificationDeliveryRecord) -> NotificationDeliveryLog:
    if not isinstance(record, NotificationDeliveryRecord):
        raise TypeError("notification delivery record is required")
    try:
        current = load_notification_delivery_log(path)
    except FileNotFoundError:
        current = NotificationDeliveryLog(())
    updated = NotificationDeliveryLog(current.records + (record,))
    save_notification_delivery_log(path, updated)
    return updated


def save_notification_delivery_log(path: Path, log: NotificationDeliveryLog) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("notification delivery log path must be absolute")
    if not isinstance(log, NotificationDeliveryLog):
        raise TypeError("notification delivery log is required")
    if path.is_symlink():
        raise ValueError("notification delivery log path must not be a symlink")
    ensure_private_directory(path.parent)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(log.to_data(), output, allow_nan=False, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    enforce_private_file(path)
    return path


def load_notification_delivery_log(path: Path) -> NotificationDeliveryLog:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("notification delivery log path must be absolute")
    enforce_private_file(path)
    try:
        return NotificationDeliveryLog.from_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("notification delivery log cannot be loaded") from error


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
