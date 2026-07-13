# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from solomon.api.auth import TENANT_READ_SCOPE, validate_auth_scopes
from solomon.api.tenancy import hash_api_key, verify_api_key

ServicePrincipalStatus = Literal["active", "revoked"]
SERVICE_PRINCIPAL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{2,63}$")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ServicePrincipalNotFoundError(RuntimeError):
    pass


class ServicePrincipalAlreadyExistsError(RuntimeError):
    pass


class ServicePrincipalRecord(BaseModel):
    principal_id: str
    tenant_id: str
    status: ServicePrincipalStatus = "active"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    key_hash: str
    scopes: list[str] = Field(default_factory=lambda: [TENANT_READ_SCOPE])

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        return validate_auth_scopes(value)


class ServicePrincipalRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def list_principals(self, *, tenant_id: str | None = None) -> list[ServicePrincipalRecord]:
        with self._lock:
            records = self._read_unlocked()
        values = list(records.values())
        if tenant_id is not None:
            values = [record for record in values if record.tenant_id == tenant_id]
        return sorted(values, key=lambda record: record.principal_id)

    def create(
        self,
        *,
        principal_id: str,
        tenant_id: str,
        scopes: list[str] | None = None,
    ) -> tuple[ServicePrincipalRecord, str]:
        self._validate_id(principal_id)
        credential = _new_credential()
        with self._lock:
            records = self._read_unlocked()
            if principal_id in records:
                raise ServicePrincipalAlreadyExistsError(principal_id)
            now = _now()
            record = ServicePrincipalRecord(
                principal_id=principal_id,
                tenant_id=tenant_id,
                created_at=now,
                updated_at=now,
                key_hash=hash_api_key(credential),
                scopes=scopes or [TENANT_READ_SCOPE],
            )
            records[principal_id] = record
            self._write_unlocked(records)
        return record, credential

    def rotate(self, principal_id: str) -> tuple[ServicePrincipalRecord, str]:
        credential = _new_credential()
        with self._lock:
            records = self._read_unlocked()
            record = records.get(principal_id)
            if record is None:
                raise ServicePrincipalNotFoundError(principal_id)
            if record.status != "active":
                raise ValueError("revoked service principal cannot rotate")
            updated = record.model_copy(update={"key_hash": hash_api_key(credential), "updated_at": _now()})
            records[principal_id] = updated
            self._write_unlocked(records)
        return updated, credential

    def revoke(self, principal_id: str) -> ServicePrincipalRecord:
        with self._lock:
            records = self._read_unlocked()
            record = records.get(principal_id)
            if record is None:
                raise ServicePrincipalNotFoundError(principal_id)
            updated = record.model_copy(update={"status": "revoked", "updated_at": _now()})
            records[principal_id] = updated
            self._write_unlocked(records)
        return updated

    def authenticate(self, *, tenant_id: str, credential: str | None) -> ServicePrincipalRecord | None:
        if credential is None:
            return None
        with self._lock:
            records = self._read_unlocked()
        for record in records.values():
            matches_tenant = record.tenant_id == tenant_id
            if matches_tenant and record.status == "active" and verify_api_key(credential, record.key_hash):
                return record
        return None

    def _read_unlocked(self) -> dict[str, ServicePrincipalRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        records: dict[str, ServicePrincipalRecord] = {}
        for principal_id, raw in payload.get("service_principals", {}).items():
            if isinstance(raw, dict) and "principal_id" not in raw:
                raw = {**raw, "principal_id": principal_id}
            record = ServicePrincipalRecord.model_validate(raw)
            records[record.principal_id] = record
        return records

    def _write_unlocked(self, records: dict[str, ServicePrincipalRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "service_principals": {key: value.model_dump(mode="json") for key, value in records.items()},
        }
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _validate_id(principal_id: str) -> None:
        if SERVICE_PRINCIPAL_ID_RE.fullmatch(principal_id) is None:
            raise ValueError("invalid service principal id")


def _new_credential() -> str:
    return f"solomon_sp_{secrets.token_urlsafe(32)}"
