# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from cryptography.fernet import InvalidToken
from pydantic import Field, ValidationError

from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.audit.journal import AuditJournal
from solomon.currency.models import now_utc
from solomon.store.encryption import EncryptedArtifactManifest, EncryptedArtifactStore
from solomon.store.sqlite import SQLiteKnowledgeStore

ARCHIVE_MANIFEST_NAME = "backup-manifest.json"


class BackupError(RuntimeError):
    """Raised when a backup cannot be safely created, restored, or verified."""


class BackupFile(SolomonModel):
    path: str = Field(min_length=1)
    bytes: int = Field(ge=0)
    sha256: str = Field(min_length=64, max_length=64)


class BackupArchiveManifest(SolomonModel):
    schema_id: Literal["solomon.backup_archive.v1"] = "solomon.backup_archive.v1"
    created_at: datetime
    files: list[BackupFile]


class EncryptedBackupManifest(SolomonModel):
    schema_id: Literal["solomon.encrypted_backup.v1"] = "solomon.encrypted_backup.v1"
    encrypted_artifact: EncryptedArtifactManifest
    encrypted_sha256: str = Field(min_length=64, max_length=64)
    archive_sha256: str = Field(min_length=64, max_length=64)


class BackupResult(SolomonModel):
    archive_path: str
    manifest_path: str
    files: int = Field(ge=0)


class RestoreResult(SolomonModel):
    destination: str
    files: int = Field(ge=0)


class RecoveryDrillReport(SolomonModel):
    archive_path: str
    knowledge_items: int = Field(ge=0)
    knowledge_events: int = Field(ge=0)
    sqlite_databases_checked: int = Field(ge=1)
    audit_entries: int = Field(ge=0)


def backup_manifest_path(archive: Path | str) -> Path:
    path = Path(archive)
    return path.with_name(f"{path.name}.manifest.json")


def create_encrypted_backup(
    *,
    data_dir: Path | str,
    journal_dir: Path | str,
    destination: Path | str,
    passphrase: str,
) -> BackupResult:
    source_data = _require_directory(data_dir, label="data")
    source_journal = _require_directory(journal_dir, label="journal")
    target = Path(destination)
    sidecar = backup_manifest_path(target)
    if target.exists() or sidecar.exists():
        raise BackupError("backup destination or manifest already exists")
    if not passphrase:
        raise BackupError("backup passphrase is required")
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="solomon-backup-", dir=target.parent) as temporary:
        work_dir = Path(temporary)
        staged = work_dir / "staged"
        _copy_tree(source_data, staged / "data", sqlite_consistent=True)
        _copy_tree(source_journal, staged / "journal", sqlite_consistent=False)
        _verify_staged_journal(staged / "journal")
        archive = work_dir / "backup.tar"
        archive_manifest = _write_archive(staged, archive)
        encrypted = work_dir / "backup.enc"
        artifact = (
            EncryptedArtifactStore(passphrase=passphrase)
            .encrypt_file(archive, encrypted)
            .model_copy(update={"path": str(target)})
        )
        manifest = EncryptedBackupManifest(
            encrypted_artifact=artifact,
            encrypted_sha256=_sha256_file(encrypted),
            archive_sha256=_sha256_file(archive),
        )
        manifest_temp = work_dir / "backup.manifest.json"
        manifest_temp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        os.replace(encrypted, target)
        os.replace(manifest_temp, sidecar)
    return BackupResult(archive_path=str(target), manifest_path=str(sidecar), files=len(archive_manifest.files))


def restore_encrypted_backup(
    archive: Path | str,
    destination: Path | str,
    *,
    passphrase: str,
) -> RestoreResult:
    encrypted_path = Path(archive)
    target = Path(destination)
    if not encrypted_path.is_file():
        raise BackupError("backup archive does not exist")
    if target.exists():
        raise BackupError("restore destination must not already exist")
    if not passphrase:
        raise BackupError("backup passphrase is required")
    manifest = _read_encrypted_manifest(backup_manifest_path(encrypted_path))
    if not hmac.compare_digest(_sha256_file(encrypted_path), manifest.encrypted_sha256):
        raise BackupError("encrypted backup digest does not match manifest")

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="solomon-restore-", dir=target.parent) as temporary:
        work_dir = Path(temporary)
        decrypted = work_dir / "backup.tar"
        try:
            EncryptedArtifactStore(passphrase=passphrase).decrypt_file(
                encrypted_path,
                decrypted,
                manifest=manifest.encrypted_artifact,
            )
        except InvalidToken as exc:
            raise BackupError("backup cannot be decrypted with the supplied passphrase") from exc
        if not hmac.compare_digest(_sha256_file(decrypted), manifest.archive_sha256):
            raise BackupError("decrypted backup digest does not match manifest")
        staged = work_dir / "staged"
        archive_manifest = _extract_archive(decrypted, staged)
        os.replace(staged, target)
    return RestoreResult(destination=str(target), files=len(archive_manifest.files))


def run_recovery_drill(archive: Path | str, *, passphrase: str) -> RecoveryDrillReport:
    encrypted_path = Path(archive)
    with tempfile.TemporaryDirectory(prefix="solomon-recovery-drill-") as temporary:
        restored_root = Path(temporary) / "fresh-deployment"
        restore_encrypted_backup(encrypted_path, restored_root, passphrase=passphrase)
        data_dir = restored_root / "data"
        journal_dir = restored_root / "journal"
        sqlite_paths = sorted(data_dir.rglob("*.sqlite3"))
        if not sqlite_paths:
            raise BackupError("restored backup contains no SQLite databases")
        for database in sqlite_paths:
            _verify_sqlite_database(database)
        knowledge_path = data_dir / "solomon.sqlite3"
        if not knowledge_path.is_file():
            raise BackupError("restored backup does not contain solomon.sqlite3")
        service = SolomonService(data_dir=data_dir, journal_dir=journal_dir)
        if not isinstance(service.store, SQLiteKnowledgeStore):
            raise BackupError("recovery drill expected a SQLite knowledge store")
        knowledge_items = len(service.store.get_many())
        knowledge_events = len(service.store.list_events())
        audit = AuditJournal(journal_dir / "journal.jsonl").verify()
        if not audit.ok:
            raise BackupError(f"restored audit journal failed verification: {audit.error}")
    return RecoveryDrillReport(
        archive_path=str(encrypted_path),
        knowledge_items=knowledge_items,
        knowledge_events=knowledge_events,
        sqlite_databases_checked=len(sqlite_paths),
        audit_entries=audit.entries,
    )


def _require_directory(path: Path | str, *, label: str) -> Path:
    directory = Path(path)
    if not directory.is_dir() or directory.is_symlink():
        raise BackupError(f"{label} directory does not exist or is not a directory")
    return directory


def _copy_tree(source: Path, destination: Path, *, sqlite_consistent: bool) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            raise BackupError(f"backup refuses symlinked path: {path}")
        if path.is_dir():
            target.mkdir()
            continue
        if not path.is_file():
            raise BackupError(f"backup refuses non-regular path: {path}")
        if sqlite_consistent and _is_sqlite_companion(path):
            continue
        if sqlite_consistent and path.suffix == ".sqlite3":
            _copy_sqlite_database(path, target)
            continue
        shutil.copyfile(path, target)


def _is_sqlite_companion(path: Path) -> bool:
    base_name = path.name.rsplit("-", 1)[0]
    return path.name.endswith(("-journal", "-shm", "-wal")) and path.with_name(base_name).suffix == ".sqlite3"


def _copy_sqlite_database(source: Path, destination: Path) -> None:
    try:
        with sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True) as origin:
            with sqlite3.connect(destination) as copied:
                origin.backup(copied)
    except sqlite3.Error as exc:
        raise BackupError(f"unable to create consistent SQLite backup for {source}") from exc


def _write_archive(staged: Path, destination: Path) -> BackupArchiveManifest:
    files = [_backup_file(staged, path) for path in sorted(staged.rglob("*")) if path.is_file()]
    manifest = BackupArchiveManifest(created_at=now_utc(), files=files)
    manifest_path = staged / ARCHIVE_MANIFEST_NAME
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    with tarfile.open(destination, "w") as archive:
        for path in sorted(staged.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=path.relative_to(staged).as_posix(), recursive=False)
    return manifest


def _backup_file(root: Path, path: Path) -> BackupFile:
    return BackupFile(
        path=path.relative_to(root).as_posix(),
        bytes=path.stat().st_size,
        sha256=_sha256_file(path),
    )


def _read_encrypted_manifest(path: Path) -> EncryptedBackupManifest:
    try:
        return EncryptedBackupManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise BackupError("backup manifest is missing or invalid") from exc


def _extract_archive(archive_path: Path, destination: Path) -> BackupArchiveManifest:
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise BackupError("backup archive contains duplicate paths")
        for member in members:
            _validate_member(member)
        manifest_member = next((member for member in members if member.name == ARCHIVE_MANIFEST_NAME), None)
        if manifest_member is None:
            raise BackupError("backup archive does not contain its manifest")
        stream = archive.extractfile(manifest_member)
        if stream is None:
            raise BackupError("backup archive manifest cannot be read")
        try:
            manifest = BackupArchiveManifest.model_validate_json(stream.read())
        except (ValidationError, ValueError) as exc:
            raise BackupError("backup archive manifest is invalid") from exc
        _validate_manifest_paths(manifest)
        expected = {file.path for file in manifest.files}
        actual = set(names) - {ARCHIVE_MANIFEST_NAME}
        if actual != expected:
            raise BackupError("backup archive contents do not match its manifest")
        destination.mkdir()
        for member in members:
            if member.name == ARCHIVE_MANIFEST_NAME:
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise BackupError(f"backup archive member cannot be read: {member.name}")
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as extracted:
                shutil.copyfileobj(stream, extracted)
        for file in manifest.files:
            extracted_path = destination.joinpath(*PurePosixPath(file.path).parts)
            if extracted_path.stat().st_size != file.bytes or not hmac.compare_digest(
                _sha256_file(extracted_path), file.sha256
            ):
                raise BackupError(f"backup archive integrity failed for {file.path}")
    return manifest


def _validate_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if member.name == ARCHIVE_MANIFEST_NAME:
        if not member.isfile():
            raise BackupError("backup archive manifest must be a regular file")
        return
    if (
        not member.isfile()
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] not in {"data", "journal"}
    ):
        raise BackupError(f"unsafe backup archive member: {member.name}")


def _validate_manifest_paths(manifest: BackupArchiveManifest) -> None:
    paths = [file.path for file in manifest.files]
    if len(paths) != len(set(paths)):
        raise BackupError("backup manifest contains duplicate paths")
    for path in paths:
        pure_path = PurePosixPath(path)
        unsafe = pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.parts
        if unsafe or pure_path.parts[0] not in {"data", "journal"}:
            raise BackupError(f"unsafe backup manifest path: {path}")


def _verify_sqlite_database(path: Path) -> None:
    try:
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as database:
            result = database.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f"restored SQLite database is unreadable: {path}") from exc
    if result is None or result[0] != "ok":
        raise BackupError(f"restored SQLite database integrity check failed: {path}")


def _verify_staged_journal(journal_dir: Path) -> None:
    journal_path = journal_dir / "journal.jsonl"
    if not journal_path.is_file():
        return
    verification = AuditJournal(journal_path).verify()
    if not verification.ok:
        raise BackupError(f"backup audit journal failed verification: {verification.error}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
