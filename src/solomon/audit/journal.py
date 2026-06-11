# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem, now_utc
from solomon.graph.models import ImpactResult
from solomon.orchestrator.models import ModelCallAudit
from solomon.orchestrator.retrieval import RecallResult

GENESIS_HASH = "GENESIS"


class AuditEntry(SolomonModel):
    seq: int
    event_type: str
    occurred_at: datetime = Field(default_factory=now_utc)
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        from solomon.currency.models import _ensure_aware_utc

        return _ensure_aware_utc(value)

    def to_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class JournalVerification(SolomonModel):
    ok: bool
    entries: int
    error: str | None = None


class AuditPackVerification(SolomonModel):
    ok: bool
    journal: JournalVerification
    manifest_hash_ok: bool


class KnowledgeReport(SolomonModel):
    as_of: datetime
    matter_id: str | None = None
    client_id: str | None = None
    items: list[dict[str, Any]]


def _canonical_event(seq: int, event_type: str, occurred_at: datetime, payload: dict[str, Any], prev_hash: str) -> str:
    return json.dumps(
        {
            "seq": seq,
            "event_type": event_type,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _entry_hash(seq: int, event_type: str, occurred_at: datetime, payload: dict[str, Any], prev_hash: str) -> str:
    message = _canonical_event(seq, event_type, occurred_at, payload, prev_hash).encode("utf-8")
    return hashlib.sha256(message).hexdigest()


@dataclass(frozen=True)
class AuditPack:
    directory: Path
    manifest_path: Path
    journal_path: Path


class AuditJournal:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        occurred_at: datetime | None = None,
    ) -> AuditEntry:
        last = self._last_entry()
        seq = 1 if last is None else last.seq + 1
        prev_hash = GENESIS_HASH if last is None else last.entry_hash
        timestamp = occurred_at or now_utc()
        entry_hash = _entry_hash(seq, event_type, timestamp, payload, prev_hash)
        entry = AuditEntry(
            seq=seq,
            event_type=event_type,
            occurred_at=timestamp,
            payload=payload,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(entry.to_json())
            fh.write("\n")
        return entry

    def log_query(
        self,
        *,
        query_id: str,
        results: list[RecallResult],
        model_audit: ModelCallAudit | None = None,
        verification_ran: bool = False,
    ) -> AuditEntry:
        payload: dict[str, Any] = {
            "query_id": query_id,
            "result_items": [
                {
                    "item_id": result.item.id,
                    "currency_state": result.currency_state.value,
                    "dependency_ids": [edge.id for edge in result.dependencies],
                    "last_verified_at": result.last_verified_at.isoformat() if result.last_verified_at else None,
                }
                for result in results
            ],
            "verification_ran": verification_ran,
        }
        if model_audit is not None:
            payload["model"] = model_audit.model_dump(mode="json")
        return self.append("query", payload)

    def log_impact(self, impact: ImpactResult) -> AuditEntry:
        return self.append("impact", impact.model_dump(mode="json"))

    def record_erasure_tombstone(self, *, subject_ref: str, lawful_basis: str, by: str) -> AuditEntry:
        return self.append(
            "erasure_tombstone",
            {
                "subject_ref_sha256": hashlib.sha256(subject_ref.encode("utf-8")).hexdigest(),
                "lawful_basis": lawful_basis,
                "by": by,
                "mode": "tombstone-without-knowledge-delete",
            },
        )

    def export_pack(self, directory: Path | str) -> AuditPack:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        journal_copy = target / "journal.jsonl"
        shutil.copyfile(self.path, journal_copy)
        journal_hash = hashlib.sha256(journal_copy.read_bytes()).hexdigest()
        manifest = {
            "schema": "solomon.audit_pack.v1",
            "journal_file": journal_copy.name,
            "journal_sha256": journal_hash,
        }
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        manifest["manifest_sha256"] = manifest_hash
        manifest_path = target / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2), encoding="utf-8")
        return AuditPack(directory=target, manifest_path=manifest_path, journal_path=journal_copy)

    @staticmethod
    def verify_pack(directory: Path | str) -> AuditPackVerification:
        target = Path(directory)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        supplied_manifest_hash = str(manifest.pop("manifest_sha256"))
        manifest_bytes = json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8")
        manifest_hash_ok = hashlib.sha256(manifest_bytes).hexdigest() == supplied_manifest_hash
        journal_path = target / str(manifest["journal_file"])
        journal_hash_ok = hashlib.sha256(journal_path.read_bytes()).hexdigest() == manifest["journal_sha256"]
        journal = AuditJournal(journal_path).verify()
        return AuditPackVerification(
            ok=manifest_hash_ok and journal_hash_ok and journal.ok,
            journal=journal,
            manifest_hash_ok=manifest_hash_ok and journal_hash_ok,
        )

    def verify(self) -> JournalVerification:
        previous = GENESIS_HASH
        count = 0
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                count += 1
                entry = AuditEntry.model_validate_json(line)
                expected = _entry_hash(
                    entry.seq,
                    entry.event_type,
                    entry.occurred_at,
                    entry.payload,
                    entry.prev_hash,
                )
                if entry.prev_hash != previous:
                    return JournalVerification(ok=False, entries=count, error=f"bad prev_hash at seq {entry.seq}")
                if entry.entry_hash != expected:
                    return JournalVerification(ok=False, entries=count, error=f"bad entry_hash at seq {entry.seq}")
                previous = entry.entry_hash
        except Exception as exc:
            return JournalVerification(ok=False, entries=count, error=str(exc))
        return JournalVerification(ok=True, entries=count)

    def _last_entry(self) -> AuditEntry | None:
        last_line: str | None = None
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                last_line = line
        if last_line is None:
            return None
        return AuditEntry.model_validate_json(last_line)


def knowledge_metadata_snapshot(items: list[KnowledgeItem]) -> list[dict[str, Any]]:
    return [
        {
            "item_id": item.id,
            "kind": item.kind.value,
            "currency_state": item.currency_state.value,
            "credence_tier": item.credence_tier.value,
            "valid_from": item.valid_from.isoformat(),
            "valid_to": item.valid_to.isoformat() if item.valid_to else None,
            "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
            "verified_by": item.verified_by,
            "matter_id": item.matter_id,
            "client_id": item.client_id,
        }
        for item in items
    ]


def what_did_we_know_report(
    items: list[KnowledgeItem],
    *,
    as_of: datetime,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> KnowledgeReport:
    scoped = [
        item
        for item in items
        if (matter_id is None or item.matter_id == matter_id) and (client_id is None or item.client_id == client_id)
    ]
    return KnowledgeReport(
        as_of=as_of,
        matter_id=matter_id,
        client_id=client_id,
        items=knowledge_metadata_snapshot(scoped),
    )
