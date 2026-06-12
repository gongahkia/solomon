# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

TenantStatus = Literal["active", "suspended"]

TENANT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 240_000


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TenantRegistryError(RuntimeError):
    """Base error for tenant registry operations."""


class TenantAlreadyExistsError(TenantRegistryError):
    """Raised when creating a tenant that already exists."""


class TenantNotFoundError(TenantRegistryError):
    """Raised when a tenant does not exist."""


class TenantRecord(BaseModel):
    tenant_id: str
    display_name: str | None = None
    status: TenantStatus = "active"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    api_key_hash: str | None = None

    @property
    def api_key_configured(self) -> bool:
        return self.api_key_hash is not None


class TenantRegistry:
    """Durable JSON tenant registry for small self-hosted server deployments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def list_tenants(self) -> list[TenantRecord]:
        with self._lock:
            records = self._read_records_unlocked()
        return sorted(records.values(), key=lambda record: record.tenant_id)

    def get(self, tenant_id: str) -> TenantRecord | None:
        with self._lock:
            return self._read_records_unlocked().get(tenant_id)

    def ensure_tenant(
        self,
        tenant_id: str,
        *,
        display_name: str | None = None,
        api_key: str | None = None,
    ) -> TenantRecord:
        self._validate_tenant_id(tenant_id)
        with self._lock:
            records = self._read_records_unlocked()
            existing = records.get(tenant_id)
            if existing is not None:
                return existing
            now = _now()
            record = TenantRecord(
                tenant_id=tenant_id,
                display_name=display_name,
                status="active",
                created_at=now,
                updated_at=now,
                api_key_hash=hash_api_key(api_key) if api_key else None,
            )
            records[tenant_id] = record
            self._write_records_unlocked(records)
            return record

    def create_tenant(
        self,
        tenant_id: str,
        *,
        display_name: str | None = None,
        api_key: str | None = None,
    ) -> TenantRecord:
        self._validate_tenant_id(tenant_id)
        with self._lock:
            records = self._read_records_unlocked()
            if tenant_id in records:
                raise TenantAlreadyExistsError(tenant_id)
            now = _now()
            record = TenantRecord(
                tenant_id=tenant_id,
                display_name=display_name,
                status="active",
                created_at=now,
                updated_at=now,
                api_key_hash=hash_api_key(api_key) if api_key else None,
            )
            records[tenant_id] = record
            self._write_records_unlocked(records)
            return record

    def suspend_tenant(self, tenant_id: str) -> TenantRecord:
        return self._set_status(tenant_id, "suspended")

    def reactivate_tenant(self, tenant_id: str) -> TenantRecord:
        return self._set_status(tenant_id, "active")

    def verify_tenant_api_key(self, record: TenantRecord, supplied_api_key: str | None) -> bool:
        if record.api_key_hash is None or supplied_api_key is None:
            return False
        return verify_api_key(supplied_api_key, record.api_key_hash)

    def _set_status(self, tenant_id: str, status: TenantStatus) -> TenantRecord:
        self._validate_tenant_id(tenant_id)
        with self._lock:
            records = self._read_records_unlocked()
            record = records.get(tenant_id)
            if record is None:
                raise TenantNotFoundError(tenant_id)
            updated = record.model_copy(update={"status": status, "updated_at": _now()})
            records[tenant_id] = updated
            self._write_records_unlocked(records)
            return updated

    def _read_records_unlocked(self) -> dict[str, TenantRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        tenants = payload.get("tenants", {})
        records: dict[str, TenantRecord] = {}
        for tenant_id, raw_record in tenants.items():
            if isinstance(raw_record, dict) and "tenant_id" not in raw_record:
                raw_record = {**raw_record, "tenant_id": tenant_id}
            record = TenantRecord.model_validate(raw_record)
            records[record.tenant_id] = record
        return records

    def _write_records_unlocked(self, records: dict[str, TenantRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "tenants": {
                tenant_id: record.model_dump(mode="json")
                for tenant_id, record in sorted(records.items(), key=lambda item: item[0])
            },
        }
        tmp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    @staticmethod
    def _validate_tenant_id(tenant_id: str) -> None:
        if not is_valid_tenant_id(tenant_id):
            raise ValueError(f"invalid tenant id: {tenant_id!r}")


def is_valid_tenant_id(tenant_id: str) -> bool:
    return TENANT_ID_RE.fullmatch(tenant_id) is not None


def hash_api_key(api_key: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", api_key.encode("utf-8"), salt, _HASH_ITERATIONS)
    encoded_salt = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    encoded_digest = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{_HASH_ALGORITHM}${_HASH_ITERATIONS}${encoded_salt}${encoded_digest}"


def verify_api_key(api_key: str, encoded_hash: str) -> bool:
    try:
        algorithm, raw_iterations, encoded_salt, encoded_digest = encoded_hash.split("$", maxsplit=3)
        if algorithm != _HASH_ALGORITHM:
            return False
        iterations = int(raw_iterations)
        salt = _decode_base64url(encoded_salt)
        expected = _decode_base64url(encoded_digest)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", api_key.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _decode_base64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
