from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory
from stonks_cli.vnext.foundation import Clock, as_utc
from stonks_cli.vnext.notification_delivery_log import (
    NotificationDeliveryStatus,
    load_notification_delivery_log,
)

OPERATOR_ACKNOWLEDGEMENT_LOG_VERSION = 1
_OPERATOR_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@-]*\Z")


@dataclass(frozen=True)
class OperatorAcknowledgement:
    acknowledgement_id: UUID
    delivery_id: UUID
    operator_id: str
    acknowledged_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.acknowledgement_id, UUID) or not isinstance(self.delivery_id, UUID):
            raise TypeError("operator acknowledgement IDs must be UUIDs")
        if not isinstance(self.operator_id, str) or not _OPERATOR_ID_PATTERN.fullmatch(self.operator_id):
            raise ValueError("operator acknowledgement operator ID is invalid")
        object.__setattr__(self, "acknowledged_at", as_utc(self.acknowledged_at))

    def to_data(self) -> dict[str, object]:
        return {
            "acknowledgement_id": str(self.acknowledgement_id),
            "delivery_id": str(self.delivery_id),
            "operator_id": self.operator_id,
            "acknowledged_at": self.acknowledged_at.isoformat().replace("+00:00", "Z"),
        }

    @classmethod
    def from_data(cls, data: object) -> OperatorAcknowledgement:
        if not isinstance(data, dict) or set(data) != {"acknowledgement_id", "delivery_id", "operator_id", "acknowledged_at"}:
            raise ValueError("operator acknowledgement fields are invalid")
        if not all(isinstance(data[field], str) for field in ("acknowledgement_id", "delivery_id", "operator_id", "acknowledged_at")):
            raise ValueError("operator acknowledgement fields are invalid")
        try:
            return cls(UUID(data["acknowledgement_id"]), UUID(data["delivery_id"]), data["operator_id"], datetime.fromisoformat(data["acknowledged_at"]))
        except (TypeError, ValueError) as error:
            raise ValueError("operator acknowledgement is malformed") from error


@dataclass(frozen=True)
class OperatorAcknowledgementLog:
    acknowledgements: tuple[OperatorAcknowledgement, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.acknowledgements, tuple) or not all(
            isinstance(acknowledgement, OperatorAcknowledgement) for acknowledgement in self.acknowledgements
        ):
            raise ValueError("operator acknowledgement log records are invalid")
        if len({acknowledgement.acknowledgement_id for acknowledgement in self.acknowledgements}) != len(self.acknowledgements):
            raise ValueError("operator acknowledgement log IDs must be unique")
        if len({acknowledgement.delivery_id for acknowledgement in self.acknowledgements}) != len(self.acknowledgements):
            raise ValueError("operator acknowledgement delivery IDs must be unique")
        timestamps = tuple(acknowledgement.acknowledged_at for acknowledgement in self.acknowledgements)
        if timestamps != tuple(sorted(timestamps)):
            raise ValueError("operator acknowledgement log records must be chronological")

    def to_data(self) -> dict[str, object]:
        return {
            "version": OPERATOR_ACKNOWLEDGEMENT_LOG_VERSION,
            "acknowledgements": [acknowledgement.to_data() for acknowledgement in self.acknowledgements],
        }

    @classmethod
    def from_data(cls, data: object) -> OperatorAcknowledgementLog:
        if not isinstance(data, dict) or set(data) != {"version", "acknowledgements"} or data["version"] != OPERATOR_ACKNOWLEDGEMENT_LOG_VERSION:
            raise ValueError("operator acknowledgement log fields are invalid")
        if not isinstance(data["acknowledgements"], list):
            raise ValueError("operator acknowledgement log records are invalid")
        try:
            return cls(tuple(OperatorAcknowledgement.from_data(item) for item in data["acknowledgements"]))
        except (TypeError, ValueError) as error:
            raise ValueError("operator acknowledgement log is malformed") from error


def record_operator_acknowledgement(
    acknowledgement_path: Path,
    delivery_log_path: Path,
    delivery_id: UUID,
    operator_id: str,
    clock: Clock,
    *,
    acknowledgement_id: UUID | None = None,
) -> OperatorAcknowledgement:
    if not isinstance(delivery_id, UUID):
        raise TypeError("operator acknowledgement delivery ID must be a UUID")
    if not isinstance(operator_id, str) or not _OPERATOR_ID_PATTERN.fullmatch(operator_id):
        raise ValueError("operator acknowledgement operator ID is invalid")
    if not hasattr(clock, "now") or not callable(clock.now):
        raise TypeError("operator acknowledgement clock is invalid")
    delivery_log = load_notification_delivery_log(delivery_log_path)
    delivery = next((record for record in delivery_log.records if record.delivery_id == delivery_id), None)
    if delivery is None:
        raise ValueError("operator acknowledgement delivery is not logged")
    if delivery.status is not NotificationDeliveryStatus.DELIVERED:
        raise ValueError("operator acknowledgement delivery is not delivered")
    try:
        current = load_operator_acknowledgement_log(acknowledgement_path)
    except FileNotFoundError:
        current = OperatorAcknowledgementLog(())
    if any(acknowledgement.delivery_id == delivery_id for acknowledgement in current.acknowledgements):
        raise ValueError("operator acknowledgement delivery is already acknowledged")
    timestamp = as_utc(clock.now())
    if timestamp < delivery.attempted_at or current.acknowledgements and timestamp < current.acknowledgements[-1].acknowledged_at:
        raise ValueError("operator acknowledgement timestamp is invalid")
    record = OperatorAcknowledgement(acknowledgement_id or uuid4(), delivery_id, operator_id, timestamp)
    save_operator_acknowledgement_log(acknowledgement_path, OperatorAcknowledgementLog(current.acknowledgements + (record,)))
    return record


def save_operator_acknowledgement_log(path: Path, log: OperatorAcknowledgementLog) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("operator acknowledgement log path must be absolute")
    if not isinstance(log, OperatorAcknowledgementLog):
        raise TypeError("operator acknowledgement log is required")
    if path.is_symlink():
        raise ValueError("operator acknowledgement log path must not be a symlink")
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


def load_operator_acknowledgement_log(path: Path) -> OperatorAcknowledgementLog:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("operator acknowledgement log path must be absolute")
    enforce_private_file(path)
    try:
        return OperatorAcknowledgementLog.from_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("operator acknowledgement log cannot be loaded") from error


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
