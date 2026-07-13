# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.api.service import IngestRequest, SolomonService
from solomon.backup import BackupError, create_encrypted_backup, restore_encrypted_backup, run_recovery_drill
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.store.sqlite import SQLiteKnowledgeStore

TEST_PASSPHRASE = "unit-test-backup-passphrase"  # noqa: S105
WRONG_PASSPHRASE = "wrong-passphrase"  # noqa: S105


def _seed_service(tmp_path: Path) -> SolomonService:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="backup recovery position under Regulation R section 12",
            source_kind=SourceKind.PARTNER,
            source_ref="backup-test-memo",
        )
    )
    return service


def test_encrypted_backup_restores_fresh_deployment_and_recovery_drill(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    archive = tmp_path / "backup.enc"

    created = create_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        destination=archive,
        passphrase=TEST_PASSPHRASE,
    )

    assert created.files >= 4
    assert "backup recovery position" not in archive.read_text(encoding="latin-1")
    assert Path(created.manifest_path).is_file()

    restored_root = tmp_path / "restored"
    restored = restore_encrypted_backup(archive, restored_root, passphrase=TEST_PASSPHRASE)
    assert restored.files == created.files
    with SQLiteKnowledgeStore(restored_root / "data" / "solomon.sqlite3") as store:
        assert store.get_many()[0].content == "backup recovery position under Regulation R section 12"

    drill = run_recovery_drill(archive, passphrase=TEST_PASSPHRASE)
    assert drill.knowledge_items == 1
    assert drill.knowledge_events == 1
    assert drill.sqlite_databases_checked >= 4
    assert drill.audit_entries >= 1


def test_backup_rejects_existing_restore_target_and_wrong_passphrase(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    archive = tmp_path / "backup.enc"
    create_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        destination=archive,
        passphrase=TEST_PASSPHRASE,
    )

    with pytest.raises(BackupError, match="supplied passphrase"):
        restore_encrypted_backup(archive, tmp_path / "wrong-key", passphrase=WRONG_PASSPHRASE)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(BackupError, match="must not already exist"):
        restore_encrypted_backup(archive, existing, passphrase=TEST_PASSPHRASE)


def test_backup_rejects_tampered_encrypted_archive_before_restore(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    archive = tmp_path / "backup.enc"
    create_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        destination=archive,
        passphrase=TEST_PASSPHRASE,
    )
    encrypted = bytearray(archive.read_bytes())
    encrypted[-1] ^= 1
    archive.write_bytes(encrypted)

    with pytest.raises(BackupError, match="digest"):
        restore_encrypted_backup(archive, tmp_path / "tampered", passphrase=TEST_PASSPHRASE)


def test_backup_refuses_invalid_audit_journal(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    (tmp_path / "journal" / "journal.jsonl").write_text("not-json\n", encoding="utf-8")

    with pytest.raises(BackupError, match="audit journal failed verification"):
        create_encrypted_backup(
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            destination=tmp_path / "invalid-journal.enc",
            passphrase=TEST_PASSPHRASE,
        )
