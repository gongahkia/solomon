# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem

RetentionScope = Literal["item", "matter", "client"]
ErasureState = Literal["erased", "held"]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def subject_ref_sha256(subject_ref: str) -> str:
    return hashlib.sha256(subject_ref.encode("utf-8")).hexdigest()


class LegalHoldNotFoundError(RuntimeError):
    pass


class LegalHoldRecord(SolomonModel):
    hold_id: str = Field(min_length=1)
    scope: RetentionScope
    scope_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)
    active: bool = True
    created_at: datetime = Field(default_factory=_now)
    released_at: datetime | None = None


class ErasureRecord(SolomonModel):
    request_id: str = Field(min_length=1)
    scope: RetentionScope
    scope_id: str = Field(min_length=1)
    subject_ref_sha256: str = Field(min_length=64, max_length=64)
    lawful_basis: str = Field(min_length=1, max_length=500)
    state: ErasureState
    affected_item_ids: list[str] = Field(default_factory=list)
    legal_hold_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    completed_at: datetime = Field(default_factory=_now)


@dataclass
class _RegistryRecords:
    holds: list[LegalHoldRecord]
    erasures: list[ErasureRecord]


class RetentionRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def list_holds(self, *, active_only: bool = False) -> list[LegalHoldRecord]:
        with self._lock:
            holds = self._read_unlocked().holds
        if active_only:
            holds = [hold for hold in holds if hold.active]
        return sorted(holds, key=lambda hold: (hold.created_at, hold.hold_id))

    def create_hold(self, *, scope: RetentionScope, scope_id: str, reason: str) -> LegalHoldRecord:
        hold = LegalHoldRecord(hold_id=f"hold-{uuid.uuid4().hex}", scope=scope, scope_id=scope_id, reason=reason)
        with self._lock:
            records = self._read_unlocked()
            records.holds.append(hold)
            self._write_unlocked(records)
        return hold

    def release_hold(self, hold_id: str) -> LegalHoldRecord:
        with self._lock:
            records = self._read_unlocked()
            for index, hold in enumerate(records.holds):
                if hold.hold_id == hold_id:
                    if not hold.active:
                        return hold
                    released = LegalHoldRecord(
                        hold_id=hold.hold_id,
                        scope=hold.scope,
                        scope_id=hold.scope_id,
                        reason=hold.reason,
                        active=False,
                        created_at=hold.created_at,
                        released_at=_now(),
                    )
                    records.holds[index] = released
                    self._write_unlocked(records)
                    return released
        raise LegalHoldNotFoundError(hold_id)

    def matching_holds(self, items: list[KnowledgeItem]) -> list[LegalHoldRecord]:
        holds = self.list_holds(active_only=True)
        return [hold for hold in holds if any(_hold_matches(hold, item) for item in items)]

    def list_erasures(self) -> list[ErasureRecord]:
        with self._lock:
            erasures = self._read_unlocked().erasures
        return sorted(erasures, key=lambda record: (record.created_at, record.request_id))

    def record_erasure(
        self,
        *,
        scope: RetentionScope,
        scope_id: str,
        subject_ref: str,
        lawful_basis: str,
        state: ErasureState,
        affected_item_ids: list[str],
        legal_hold_ids: list[str] | None = None,
    ) -> ErasureRecord:
        record = ErasureRecord(
            request_id=f"erase-{uuid.uuid4().hex}",
            scope=scope,
            scope_id=scope_id,
            subject_ref_sha256=subject_ref_sha256(subject_ref),
            lawful_basis=lawful_basis,
            state=state,
            affected_item_ids=sorted(affected_item_ids),
            legal_hold_ids=sorted(legal_hold_ids or []),
        )
        with self._lock:
            records = self._read_unlocked()
            records.erasures.append(record)
            self._write_unlocked(records)
        return record

    def _read_unlocked(self) -> _RegistryRecords:
        if not self.path.exists():
            return _RegistryRecords(holds=[], erasures=[])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return _RegistryRecords(
            holds=[LegalHoldRecord.model_validate(raw) for raw in payload.get("holds", [])],
            erasures=[ErasureRecord.model_validate(raw) for raw in payload.get("erasures", [])],
        )

    def _write_unlocked(self, records: _RegistryRecords) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "holds": [hold.model_dump(mode="json") for hold in records.holds],
            "erasures": [record.model_dump(mode="json") for record in records.erasures],
        }
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def _hold_matches(hold: LegalHoldRecord, item: KnowledgeItem) -> bool:
    if hold.scope == "item":
        return hold.scope_id == item.id
    if hold.scope == "matter":
        return hold.scope_id == item.matter_id
    return hold.scope_id == item.client_id
