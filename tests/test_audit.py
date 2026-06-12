# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from solomon.audit.journal import (
    AuditJournal,
    knowledge_metadata_snapshot,
    sign_verification_attestation,
    verify_verification_attestation,
    what_did_we_know_report,
)
from solomon.credence.policy import CredenceAction, CredenceAuditEntry
from solomon.currency.models import CredenceTier, KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.orchestrator.models import EndpointKind, ModelCallAudit


def _item() -> KnowledgeItem:
    return KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.POSITION,
        content="privileged text that must not appear in audit",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo"),
        credence_tier=CredenceTier.FIRM_AUTHORITATIVE,
    )


def test_append_only_journal_verifies_and_detects_tamper(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    journal = AuditJournal(path)
    journal.append("one", {"item_id": "item-1"})
    journal.append("two", {"item_id": "item-2"})

    assert journal.verify().ok is True

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["payload"]["item_id"] = "changed"
    lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    assert journal.verify().ok is False


def test_query_logging_is_metadata_only(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    item = _item()
    model_audit = ModelCallAudit(
        endpoint=EndpointKind.LOCAL,
        reason="strict",
        crossed_boundary=False,
        prompt_sha256="a" * 64,
        prompt_chars=120,
        latency_ms=1.0,
    )

    journal.log_query(query_id="q1", results=[], model_audit=model_audit, verification_ran=True)
    journal.append("knowledge_snapshot", {"items": knowledge_metadata_snapshot([item])})

    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "privileged text" not in raw
    assert "prompt_sha256" in raw
    assert "item-1" in raw


def test_credence_change_logging_is_hash_chained(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    entry = CredenceAuditEntry(
        item_id="item-1",
        action=CredenceAction.ASSIGN,
        from_tier=CredenceTier.UNVERIFIED,
        to_tier=CredenceTier.FIRM_AUTHORITATIVE,
        by="system",
        reason="source kind partner",
    )

    journal.log_credence_change(entry)

    raw = (tmp_path / "journal.jsonl").read_text(encoding="utf-8")
    assert "credence_change" in raw
    assert "FirmAuthoritative" in raw
    assert journal.verify().ok is True


def test_audit_pack_export_and_verify(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    journal.append("event", {"item_id": "item-1"})

    pack = journal.export_pack(tmp_path / "pack")

    assert pack.manifest_path.exists()
    assert AuditJournal.verify_pack(pack.directory).ok is True


def test_erasure_tombstone_hashes_subject_without_delete(tmp_path: Path) -> None:
    journal = AuditJournal(tmp_path / "journal.jsonl")
    entry = journal.record_erasure_tombstone(subject_ref="Jane Doe", lawful_basis="GDPR Art 17", by="DPO")

    assert entry.payload["subject_ref_sha256"] != "Jane Doe"
    assert entry.payload["mode"] == "tombstone-without-knowledge-delete"


def test_what_did_we_know_report_scopes_by_matter() -> None:
    item = _item().model_copy(update={"matter_id": "matter-a"})
    other = _item().model_copy(update={"id": "item-2", "matter_id": "matter-b"})

    report = what_did_we_know_report([item, other], as_of=item.ingested_at, matter_id="matter-a")

    assert report.matter_id == "matter-a"
    assert [entry["item_id"] for entry in report.items] == ["item-1"]


def test_signed_verification_attestation_verifies_and_detects_tamper() -> None:
    item = _item().model_copy(update={"verified_by": "Partner A", "last_verified_at": _item().ingested_at})

    attestation = sign_verification_attestation(
        item,
        verified_by="Partner A",
        outcome="reaffirm",
        signing_key="test-secret",
        key_id="unit-test",
    )
    tampered = attestation.model_copy(update={"outcome": "retire"})

    assert verify_verification_attestation(attestation, signing_key="test-secret") is True
    assert verify_verification_attestation(tampered, signing_key="test-secret") is False
