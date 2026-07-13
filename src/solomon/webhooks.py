# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.contracts import WebhookDelivery, WebhookDeliveryResult
from solomon.currency.models import _ensure_aware_utc, now_utc


class WebhookDeliveryState(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class WebhookDeliveryRecord(SolomonModel):
    id: str = Field(min_length=1)
    delivery: WebhookDelivery
    payload_sha256: str = Field(min_length=64, max_length=64)
    state: WebhookDeliveryState = WebhookDeliveryState.PENDING
    attempts: int = Field(default=0, ge=0)
    status_code: int | None = Field(default=None, ge=100, le=599)
    last_error: str | None = None
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    delivered_at: datetime | None = None

    @classmethod
    def new(cls, delivery: WebhookDelivery, payload_sha256: str) -> WebhookDeliveryRecord:
        return cls(id=_delivery_id(delivery), delivery=delivery, payload_sha256=payload_sha256)

    def model_post_init(self, __context: Any) -> None:
        self.created_at = _ensure_aware_utc(self.created_at)
        self.updated_at = _ensure_aware_utc(self.updated_at)
        self.delivered_at = _ensure_aware_utc(self.delivered_at) if self.delivered_at is not None else None


class WebhookResponse(Protocol):
    status_code: int


class WebhookTransport(Protocol):
    def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> WebhookResponse: ...


class WebhookDeliveryError(ValueError):
    pass


class SQLiteWebhookDeliveryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webhook_deliveries (
                    delivery_id TEXT PRIMARY KEY,
                    target_url TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    UNIQUE(target_url, idempotency_key)
                )
                """
            )

    def close(self) -> None:
        self._conn.close()

    def get_or_create(self, delivery: WebhookDelivery, payload_sha256: str) -> tuple[WebhookDeliveryRecord, bool]:
        record = WebhookDeliveryRecord.new(delivery, payload_sha256)
        with self._conn:
            try:
                self._conn.execute(
                    """
                    INSERT INTO webhook_deliveries (delivery_id, target_url, idempotency_key, record_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (record.id, delivery.target_url, delivery.idempotency_key, record.model_dump_json()),
                )
            except sqlite3.IntegrityError:
                return self._by_target_and_key(delivery.target_url, delivery.idempotency_key), False
        return record, True

    def get(self, delivery_id: str) -> WebhookDeliveryRecord:
        row = self._conn.execute(
            "SELECT record_json FROM webhook_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if row is None:
            raise KeyError(delivery_id)
        return WebhookDeliveryRecord.model_validate_json(str(row["record_json"]))

    def list(self, *, state: WebhookDeliveryState | None = None) -> list[WebhookDeliveryRecord]:
        rows = self._conn.execute("SELECT record_json FROM webhook_deliveries ORDER BY delivery_id").fetchall()
        records = [WebhookDeliveryRecord.model_validate_json(str(row["record_json"])) for row in rows]
        return [record for record in records if state is None or record.state is state]

    def update(self, record: WebhookDeliveryRecord) -> WebhookDeliveryRecord:
        with self._conn:
            result = self._conn.execute(
                "UPDATE webhook_deliveries SET record_json = ? WHERE delivery_id = ?",
                (record.model_dump_json(), record.id),
            )
        if result.rowcount == 0:
            raise KeyError(record.id)
        return record

    def _by_target_and_key(self, target_url: str, idempotency_key: str) -> WebhookDeliveryRecord:
        row = self._conn.execute(
            "SELECT record_json FROM webhook_deliveries WHERE target_url = ? AND idempotency_key = ?",
            (target_url, idempotency_key),
        ).fetchone()
        if row is None:  # pragma: no cover - constrained by the failed insert above
            raise KeyError(idempotency_key)
        return WebhookDeliveryRecord.model_validate_json(str(row["record_json"]))


class HMACWebhookDispatcher:
    def __init__(
        self,
        *,
        signing_secret: str,
        store: SQLiteWebhookDeliveryStore,
        transport: WebhookTransport,
        max_attempts: int = 3,
        clock: Callable[[], datetime] = now_utc,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self.signing_secret = signing_secret.encode()
        self.store = store
        self.transport = transport
        self.max_attempts = max_attempts
        self.clock = clock

    def deliver(self, delivery: WebhookDelivery) -> WebhookDeliveryResult:
        _validate_target_url(delivery.target_url)
        body = _event_body(delivery)
        payload_sha256 = hashlib.sha256(body).hexdigest()
        record, created = self.store.get_or_create(delivery, payload_sha256)
        if not created and record.payload_sha256 != payload_sha256:
            raise WebhookDeliveryError("idempotency key was already used with a different event payload")
        if not created and record.state is WebhookDeliveryState.DELIVERED:
            return _result(record, idempotent_replay=True)
        headers = _signed_headers(delivery, body, self.signing_secret)
        for _ in range(self.max_attempts):
            record = record.model_copy(update={"attempts": record.attempts + 1, "updated_at": self.clock()})
            try:
                response = self.transport.post(delivery.target_url, content=body, headers=headers)
                status_code = response.status_code
                error = None
            except (ConnectionError, OSError, TimeoutError) as exc:
                status_code = 599
                error = exc.__class__.__name__
            if 200 <= status_code < 300:
                record = record.model_copy(
                    update={
                        "state": WebhookDeliveryState.DELIVERED,
                        "status_code": status_code,
                        "last_error": None,
                        "delivered_at": self.clock(),
                    }
                )
                self.store.update(record)
                return _result(record)
            record = record.model_copy(
                update={
                    "state": WebhookDeliveryState.FAILED,
                    "status_code": status_code,
                    "last_error": error or f"HTTP {status_code}",
                }
            )
            if not _retryable_status(status_code):
                break
        self.store.update(record)
        return _result(record)

    def inspect(self, delivery_id: str) -> WebhookDeliveryRecord:
        return self.store.get(delivery_id)

    def list_deliveries(self, *, state: WebhookDeliveryState | None = None) -> list[WebhookDeliveryRecord]:
        return self.store.list(state=state)


def _event_body(delivery: WebhookDelivery) -> bytes:
    return json.dumps(delivery.event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def _signed_headers(delivery: WebhookDelivery, body: bytes, secret: bytes) -> dict[str, str]:
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Solomon-Delivery-Id": _delivery_id(delivery),
        "X-Solomon-Event": delivery.event.event_type,
        "X-Solomon-Idempotency-Key": delivery.idempotency_key,
        "X-Solomon-Signature": f"sha256={signature}",
    }


def _retryable_status(status_code: int) -> bool:
    return status_code == 408 or status_code == 429 or 500 <= status_code <= 599


def _delivery_id(delivery: WebhookDelivery) -> str:
    return hashlib.sha256(f"{delivery.target_url}\n{delivery.idempotency_key}".encode()).hexdigest()[:32]


def _result(record: WebhookDeliveryRecord, *, idempotent_replay: bool = False) -> WebhookDeliveryResult:
    return WebhookDeliveryResult(
        delivery_id=record.id,
        status_code=record.status_code or 599,
        delivered_at=record.delivered_at or record.updated_at,
        attempts=record.attempts,
        idempotent_replay=idempotent_replay,
    )


def _validate_target_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise WebhookDeliveryError("webhook target URL must be an absolute https URL without credentials or fragment")


__all__ = [
    "HMACWebhookDispatcher",
    "SQLiteWebhookDeliveryStore",
    "WebhookDeliveryError",
    "WebhookDeliveryRecord",
    "WebhookDeliveryState",
    "WebhookResponse",
    "WebhookTransport",
]
