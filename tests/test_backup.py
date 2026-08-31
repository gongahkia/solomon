# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

from solomon.api.service import IngestRequest, SolomonService
from solomon.backup import (
    BackupError,
    apply_server_restore,
    create_encrypted_backup,
    create_server_encrypted_backup,
    inspect_server_encrypted_backup,
    plan_server_restore,
    postgres_dump_runner,
    postgres_restore_runner,
    restore_encrypted_backup,
    run_recovery_drill,
)
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.deployment import MaintenanceGate, initialize_deployment
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


def test_backup_rejects_missing_or_unsafe_input_paths(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="data directory"):
        create_encrypted_backup(
            data_dir=tmp_path / "missing-data",
            journal_dir=tmp_path / "missing-journal",
            destination=tmp_path / "backup.enc",
            passphrase=TEST_PASSPHRASE,
        )

    data_dir = tmp_path / "data"
    journal_dir = tmp_path / "journal"
    data_dir.mkdir()
    journal_dir.mkdir()
    existing = tmp_path / "existing.enc"
    existing.write_text("existing", encoding="utf-8")
    with pytest.raises(BackupError, match="destination"):
        create_encrypted_backup(
            data_dir=data_dir,
            journal_dir=journal_dir,
            destination=existing,
            passphrase=TEST_PASSPHRASE,
        )
    with pytest.raises(BackupError, match="passphrase"):
        create_encrypted_backup(
            data_dir=data_dir,
            journal_dir=journal_dir,
            destination=tmp_path / "empty-passphrase.enc",
            passphrase="",
        )

    unsafe_data_dir = tmp_path / "unsafe-data"
    unsafe_data_dir.mkdir()
    (unsafe_data_dir / "linked.txt").symlink_to(tmp_path / "target.txt")
    with pytest.raises(BackupError, match="symlinked"):
        create_encrypted_backup(
            data_dir=unsafe_data_dir,
            journal_dir=journal_dir,
            destination=tmp_path / "unsafe.enc",
            passphrase=TEST_PASSPHRASE,
        )


def test_restore_rejects_missing_or_invalid_archive_before_extracting(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="does not exist"):
        restore_encrypted_backup(tmp_path / "missing.enc", tmp_path / "restored", passphrase=TEST_PASSPHRASE)

    archive = tmp_path / "invalid.enc"
    archive.write_text("not an encrypted archive", encoding="utf-8")
    with pytest.raises(BackupError, match="passphrase"):
        restore_encrypted_backup(archive, tmp_path / "empty-passphrase", passphrase="")
    with pytest.raises(BackupError, match="manifest"):
        restore_encrypted_backup(archive, tmp_path / "invalid-manifest", passphrase=TEST_PASSPHRASE)


def test_restore_rejects_decrypted_archive_digest_drift(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    archive = tmp_path / "backup.enc"
    create_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        destination=archive,
        passphrase=TEST_PASSPHRASE,
    )
    manifest_path = archive.with_name(f"{archive.name}.manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["archive_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BackupError, match="decrypted backup digest"):
        restore_encrypted_backup(archive, tmp_path / "drifted", passphrase=TEST_PASSPHRASE)


def test_server_backup_and_guarded_restore_cover_postgres_and_local_state(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    database_url = "postgresql://solomon:backup-password@localhost:5432/solomon"
    metadata, _ = initialize_deployment(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
        owner="backup-test",
    )
    archive = tmp_path / "server-backup.enc"

    created = create_server_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
        destination=archive,
        passphrase=TEST_PASSPHRASE,
        dump_postgres=lambda target: target.write_bytes(b"deterministic-postgres-dump"),
        owner="backup-test",
    )
    inspected = inspect_server_encrypted_backup(archive, passphrase=TEST_PASSPHRASE)
    plan = plan_server_restore(
        archive,
        tmp_path / "server-restored",
        database_url=database_url,
        passphrase=TEST_PASSPHRASE,
    )
    restored_dumps: list[bytes] = []
    restored = apply_server_restore(
        plan,
        database_url=database_url,
        passphrase=TEST_PASSPHRASE,
        restore_postgres=lambda dump: restored_dumps.append(dump.read_bytes()),
    )

    assert created.deployment_id == inspected.deployment_id == restored.deployment_id == metadata.deployment_id
    assert created.postgres_dump_bytes == len(b"deterministic-postgres-dump")
    assert restored_dumps == [b"deterministic-postgres-dump"]
    assert (tmp_path / "server-restored" / "data" / "solomon.sqlite3").is_file()
    assert (tmp_path / "server-restored" / "data" / ".solomon-maintenance.json").exists() is False
    assert (tmp_path / "server-restored" / "journal" / "journal.jsonl").is_file()


def test_server_backup_failure_leaves_marker_and_releases_maintenance(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    database_url = "postgresql://solomon:backup-password@localhost:5432/solomon"
    initialize_deployment(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
    )

    def fail_dump(_target: Path) -> None:
        raise RuntimeError("injected dump interruption")

    with pytest.raises(RuntimeError, match="injected dump interruption"):
        create_server_encrypted_backup(
            data_dir=tmp_path / "data",
            journal_dir=tmp_path / "journal",
            database_url=database_url,
            destination=tmp_path / "server-backup.enc",
            passphrase=TEST_PASSPHRASE,
            dump_postgres=fail_dump,
        )

    assert MaintenanceGate(tmp_path / "data").active() is None
    incomplete = list(tmp_path.glob(".server-backup.enc.incomplete-*/INCOMPLETE.json"))
    assert len(incomplete) == 1


def test_server_restore_refuses_stale_plan_and_database_identity_mismatch(tmp_path: Path) -> None:
    _seed_service(tmp_path)
    database_url = "postgresql://solomon:backup-password@localhost:5432/solomon"
    initialize_deployment(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
    )
    archive = tmp_path / "server-backup.enc"
    create_server_encrypted_backup(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        database_url=database_url,
        destination=archive,
        passphrase=TEST_PASSPHRASE,
        dump_postgres=lambda target: target.write_bytes(b"postgres-dump"),
    )
    plan = plan_server_restore(
        archive,
        tmp_path / "server-restored",
        database_url=database_url,
        passphrase=TEST_PASSPHRASE,
    )
    (tmp_path / "server-restored").mkdir()

    with pytest.raises(BackupError, match="destination"):
        apply_server_restore(
            plan,
            database_url=database_url,
            passphrase=TEST_PASSPHRASE,
            restore_postgres=lambda _dump: None,
        )
    with pytest.raises(BackupError, match="database logical identity"):
        plan_server_restore(
            archive,
            tmp_path / "different-target",
            database_url="postgresql://solomon:backup-password@localhost:5432/different",
            passphrase=TEST_PASSPHRASE,
        )


def test_postgres_client_callbacks_keep_password_out_of_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    class Completed:
        returncode = 0

    def fake_run(command: list[str], **kwargs: object) -> Completed:
        calls.append((command, kwargs["env"]))  # type: ignore[arg-type,index]
        if command[0].endswith("pg_dump"):
            Path(command[command.index("--file") + 1]).write_bytes(b"dump")
        return Completed()

    monkeypatch.setattr("solomon.backup.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("solomon.backup.subprocess.run", fake_run)
    monkeypatch.setattr("solomon.backup._require_empty_postgres_database", lambda _url: None)
    database_url = "postgresql://solomon:do-not-leak@db.example:5544/solomon?sslmode=require"

    dump = tmp_path / "knowledge.dump"
    postgres_dump_runner(database_url)(dump)
    postgres_restore_runner(database_url)(dump)

    assert dump.read_bytes() == b"dump"
    assert len(calls) == 2
    assert all("do-not-leak" not in " ".join(command) for command, _environment in calls)
    assert all(environment["PGPASSWORD"] == "do-not-leak" for _command, environment in calls)
    assert all(environment["PGSSLMODE"] == "require" for _command, environment in calls)


def test_postgres_backup_restore_callbacks_refuse_missing_tools_failures_and_unsafe_input(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = "postgresql://solomon:secret@db.example/solomon"
    dump = tmp_path / "knowledge.dump"
    dump.write_bytes(b"dump")

    monkeypatch.setattr("solomon.backup.shutil.which", lambda _name: None)
    monkeypatch.setattr("solomon.backup._require_empty_postgres_database", lambda _url: None)
    with pytest.raises(BackupError, match="pg_dump is required"):
        postgres_dump_runner(database_url)(tmp_path / "new.dump")
    with pytest.raises(BackupError, match="pg_restore is required"):
        postgres_restore_runner(database_url)(dump)
    with pytest.raises(BackupError, match="input is unsafe"):
        postgres_restore_runner(database_url)(tmp_path / "missing.dump")

    class Failed:
        returncode = 1

    monkeypatch.setattr("solomon.backup.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("solomon.backup.subprocess.run", lambda *_args, **_kwargs: Failed())
    with pytest.raises(BackupError, match="logical dump failed"):
        postgres_dump_runner(database_url)(tmp_path / "failed.dump")
    with pytest.raises(BackupError, match="logical restore failed"):
        postgres_restore_runner(database_url)(dump)


def test_postgres_empty_target_guard_closes_connections_and_refuses_application_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[bool] = []

    class Cursor:
        def __init__(self, row: object) -> None:
            self.row = row

        def fetchone(self) -> object:
            return self.row

    class Connection:
        def __init__(self, row: object) -> None:
            self.row = row

        def execute(self, _query: str) -> Cursor:
            return Cursor(self.row)

        def close(self) -> None:
            closed.append(True)

    connection = Connection(None)
    monkeypatch.setattr("solomon.store.postgres.connection.default_connect", lambda _url: connection)
    from solomon.backup import _require_empty_postgres_database

    _require_empty_postgres_database("postgresql://solomon:secret@db.example/solomon")
    assert closed == [True]

    closed.clear()
    monkeypatch.setattr(
        "solomon.store.postgres.connection.default_connect", lambda _url: Connection(("knowledge_items",))
    )
    with pytest.raises(BackupError, match="must be empty"):
        _require_empty_postgres_database("postgresql://solomon:secret@db.example/solomon")
    assert closed == [True]


def test_server_backup_refuses_missing_metadata_empty_dump_and_invalid_local_copy(tmp_path: Path) -> None:
    data = tmp_path / "data"
    journal = tmp_path / "journal"
    data.mkdir()
    journal.mkdir()
    database_url = "postgresql://solomon:backup-password@localhost:5432/solomon"

    with pytest.raises(BackupError, match="metadata is required"):
        create_server_encrypted_backup(
            data_dir=data,
            journal_dir=journal,
            database_url=database_url,
            destination=tmp_path / "missing-metadata.enc",
            passphrase=TEST_PASSPHRASE,
            dump_postgres=lambda _target: None,
        )

    _seed_service(tmp_path)
    initialize_deployment(data_dir=data, journal_dir=journal, database_url=database_url)
    with pytest.raises(BackupError, match="dump was not created"):
        create_server_encrypted_backup(
            data_dir=data,
            journal_dir=journal,
            database_url=database_url,
            destination=tmp_path / "empty-dump.enc",
            passphrase=TEST_PASSPHRASE,
            dump_postgres=lambda _target: None,
        )

    invalid = data / "invalid.sqlite3"
    invalid.write_bytes(b"not a sqlite database")
    with pytest.raises(BackupError, match="consistent SQLite backup"):
        create_server_encrypted_backup(
            data_dir=data,
            journal_dir=journal,
            database_url=database_url,
            destination=tmp_path / "invalid-sqlite.enc",
            passphrase=TEST_PASSPHRASE,
            dump_postgres=lambda target: target.write_bytes(b"dump"),
        )
    with sqlite3.connect(data / "solomon.sqlite3") as database:
        assert database.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_archive_extraction_refuses_excessive_member_count_before_reading_content(tmp_path: Path) -> None:
    archive = tmp_path / "excessive-members.tar"
    with tarfile.open(archive, "w") as created:
        for index in range(10_001):
            created.addfile(tarfile.TarInfo(f"data/member-{index}"))

    from solomon.backup import _extract_archive

    with pytest.raises(BackupError, match="member-count limit"):
        _extract_archive(archive, tmp_path / "extracted")
