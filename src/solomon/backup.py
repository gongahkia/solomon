# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess  # nosec B404
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

from cryptography.fernet import InvalidToken
from pydantic import Field, ValidationError

from solomon import __version__
from solomon.api.schemas import SolomonModel
from solomon.api.service import SolomonService
from solomon.audit.journal import AuditJournal
from solomon.currency.models import now_utc
from solomon.deployment import (
    DeploymentError,
    DeploymentMetadata,
    DeploymentProfile,
    MaintenanceGate,
    profile_for_database_url,
    read_metadata,
    redact_database_url,
)
from solomon.store.encryption import EncryptedArtifactManifest, EncryptedArtifactStore
from solomon.store.sqlite import SQLiteKnowledgeStore

# This module invokes only fixed PostgreSQL client binaries without a shell.
ARCHIVE_MANIFEST_NAME = "backup-manifest.json"
SERVER_BACKUP_RECORD_NAME = "server-backup.json"
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 1_073_741_824
MAX_ARCHIVE_TOTAL_BYTES = 4_294_967_296


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


class ServerBackupRecord(SolomonModel):
    """The non-secret, encrypted-in-archive record for a mixed-store checkpoint."""

    schema_id: Literal["solomon.server_backup_record.v1"] = "solomon.server_backup_record.v1"
    deployment_id: str = Field(min_length=1)
    profile: Literal["mixed-postgresql-sqlite"] = "mixed-postgresql-sqlite"
    created_at: datetime
    app_version: str = Field(min_length=1)
    maintenance_operation_id: str = Field(min_length=1)
    database_url: str = Field(min_length=1)
    components: tuple[str, ...]
    state: Literal["complete"] = "complete"


class EncryptedServerBackupManifest(SolomonModel):
    schema_id: Literal["solomon.encrypted_server_backup.v1"] = "solomon.encrypted_server_backup.v1"
    encrypted_artifact: EncryptedArtifactManifest
    encrypted_sha256: str = Field(min_length=64, max_length=64)
    archive_sha256: str = Field(min_length=64, max_length=64)
    deployment_id: str = Field(min_length=1)
    maintenance_operation_id: str = Field(min_length=1)
    state: Literal["complete"] = "complete"


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


class ServerBackupResult(BackupResult):
    deployment_id: str
    maintenance_operation_id: str
    postgres_dump_bytes: int = Field(gt=0)


class ServerRestorePlan(SolomonModel):
    schema_id: Literal["solomon.server_restore_plan.v1"] = "solomon.server_restore_plan.v1"
    archive_path: str
    destination: str
    database_url: str
    archive_sha256: str = Field(min_length=64, max_length=64)
    plan_fingerprint: str = Field(min_length=64, max_length=64)
    deployment_id: str = Field(min_length=1)
    files: int = Field(ge=1)


class ServerRestoreResult(RestoreResult):
    deployment_id: str
    maintenance_operation_id: str


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
    _require_external_backup_destination(target, source_data, source_journal)
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


def create_server_encrypted_backup(
    *,
    data_dir: Path | str,
    journal_dir: Path | str,
    database_url: str,
    destination: Path | str,
    passphrase: str,
    dump_postgres: Callable[[Path], None],
    owner: str = "cli",
) -> ServerBackupResult:
    """Create a coordinated checkpoint for the supported mixed-store profile.

    The maintenance gate blocks new Solomon writes and worker claims while the
    per-store-consistent PostgreSQL dump, SQLite copies, and audit snapshot are
    captured. It is a coordinated checkpoint, not a distributed transaction.
    """

    source_data = _require_directory(data_dir, label="data")
    source_journal = _require_directory(journal_dir, label="journal")
    metadata = _require_mixed_metadata(source_data, database_url)
    target = Path(destination)
    sidecar = backup_manifest_path(target)
    _require_external_backup_destination(target, source_data, source_journal)
    if target.exists() or sidecar.exists():
        raise BackupError("backup destination or manifest already exists")
    if not passphrase:
        raise BackupError("backup passphrase is required")
    target.parent.mkdir(parents=True, exist_ok=True)
    gate = MaintenanceGate(source_data)
    try:
        maintenance = gate.acquire(reason="coordinated-backup", owner=owner)
    except DeploymentError as exc:
        raise BackupError(str(exc)) from exc
    completed = False
    try:
        AuditJournal(source_journal / "journal.jsonl").append_idempotent(
            "deployment_backup_started",
            {
                "deployment_id": metadata.deployment_id,
                "profile": metadata.profile.value,
                "database_backend": "postgresql",
            },
            operation_id=maintenance.operation_id,
        )
        staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.incomplete-", dir=target.parent))
        staging.chmod(0o700)
        try:
            staged = staging / "staged"
            _copy_tree(
                source_data,
                staged / "data",
                sqlite_consistent=True,
                excluded_root_names={".solomon-maintenance.json", ".solomon-maintenance.lock"},
            )
            _copy_tree(source_journal, staged / "journal", sqlite_consistent=False)
            _verify_staged_journal(staged / "journal")
            dump_path = staged / "postgres" / "knowledge.dump"
            dump_path.parent.mkdir(mode=0o700)
            dump_postgres(dump_path)
            if not dump_path.is_file() or dump_path.is_symlink() or dump_path.stat().st_size == 0:
                raise BackupError("PostgreSQL dump was not created as a non-empty regular file")
            record = ServerBackupRecord(
                deployment_id=metadata.deployment_id,
                created_at=now_utc(),
                app_version=__version__,
                maintenance_operation_id=maintenance.operation_id,
                database_url=redact_database_url(database_url),
                components=metadata.components,
            )
            (staged / SERVER_BACKUP_RECORD_NAME).write_text(record.model_dump_json(indent=2), encoding="utf-8")
            archive = staging / "backup.tar"
            archive_manifest = _write_archive(staged, archive)
            encrypted = staging / "backup.enc"
            artifact = (
                EncryptedArtifactStore(passphrase=passphrase)
                .encrypt_file(archive, encrypted)
                .model_copy(update={"path": str(target)})
            )
            manifest = EncryptedServerBackupManifest(
                encrypted_artifact=artifact,
                encrypted_sha256=_sha256_file(encrypted),
                archive_sha256=_sha256_file(archive),
                deployment_id=metadata.deployment_id,
                maintenance_operation_id=maintenance.operation_id,
            )
            manifest_temp = staging / "backup.manifest.json"
            manifest_temp.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            os.replace(encrypted, target)
            os.replace(manifest_temp, sidecar)
            completed = True
            result = ServerBackupResult(
                archive_path=str(target),
                manifest_path=str(sidecar),
                files=len(archive_manifest.files),
                deployment_id=metadata.deployment_id,
                maintenance_operation_id=maintenance.operation_id,
                postgres_dump_bytes=dump_path.stat().st_size,
            )
            shutil.rmtree(staging)
            return result
        except Exception:
            _write_incomplete_marker(staging, maintenance.operation_id)
            raise
    finally:
        try:
            gate.release(maintenance.operation_id)
        except DeploymentError as exc:
            raise BackupError("maintenance state could not be released; operator intervention is required") from exc
        if completed:
            AuditJournal(source_journal / "journal.jsonl").append_idempotent(
                "deployment_backup_completed",
                {"deployment_id": metadata.deployment_id, "archive_sha256": _sha256_file(target)},
                operation_id=maintenance.operation_id,
            )


def inspect_server_encrypted_backup(archive: Path | str, *, passphrase: str) -> ServerBackupRecord:
    """Verify encryption and archive structure without writing a restore target."""

    encrypted_path = Path(archive)
    manifest = _read_server_manifest(backup_manifest_path(encrypted_path))
    if not hmac.compare_digest(_sha256_file(encrypted_path), manifest.encrypted_sha256):
        raise BackupError("encrypted backup digest does not match manifest")
    with tempfile.TemporaryDirectory(prefix="solomon-server-backup-inspect-") as temporary:
        staged = _decrypt_and_extract_server_archive(encrypted_path, manifest, passphrase, Path(temporary))
        record = _read_server_record(staged)
    if (
        record.deployment_id != manifest.deployment_id
        or record.maintenance_operation_id != manifest.maintenance_operation_id
    ):
        raise BackupError("server backup record does not match encrypted manifest")
    return record


def plan_server_restore(
    archive: Path | str,
    destination: Path | str,
    *,
    database_url: str,
    passphrase: str,
) -> ServerRestorePlan:
    """Produce a deterministic, non-mutating plan for a fresh mixed-store restore."""

    target = Path(destination)
    if target.exists():
        raise BackupError("restore destination must not already exist")
    encrypted_path = Path(archive)
    manifest = _read_server_manifest(backup_manifest_path(encrypted_path))
    if not hmac.compare_digest(_sha256_file(encrypted_path), manifest.encrypted_sha256):
        raise BackupError("encrypted backup digest does not match manifest")
    with tempfile.TemporaryDirectory(prefix="solomon-server-restore-plan-") as temporary:
        staged = _decrypt_and_extract_server_archive(encrypted_path, manifest, passphrase, Path(temporary))
        record = _read_server_record(staged)
        _validate_server_record(record, manifest, database_url)
        files = len([path for path in staged.rglob("*") if path.is_file()])
    archive_path = str(encrypted_path.resolve())
    destination_path = str(target.resolve())
    redacted_database_url = redact_database_url(database_url)
    fingerprint_payload = {
        "archive_path": archive_path,
        "destination": destination_path,
        "database_url": redacted_database_url,
        "archive_sha256": manifest.encrypted_sha256,
        "deployment_id": record.deployment_id,
        "files": files,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return ServerRestorePlan(
        archive_path=archive_path,
        destination=destination_path,
        database_url=redacted_database_url,
        archive_sha256=manifest.encrypted_sha256,
        deployment_id=record.deployment_id,
        files=files,
        plan_fingerprint=fingerprint,
    )


def apply_server_restore(
    plan: ServerRestorePlan,
    *,
    database_url: str,
    passphrase: str,
    restore_postgres: Callable[[Path], None],
) -> ServerRestoreResult:
    """Apply one unchanged plan to an absent local target and an empty database target."""

    expected = plan_server_restore(
        plan.archive_path,
        plan.destination,
        database_url=database_url,
        passphrase=passphrase,
    )
    if expected.plan_fingerprint != plan.plan_fingerprint:
        raise BackupError("restore plan is stale or has been modified")
    destination = Path(plan.destination)
    encrypted_path = Path(plan.archive_path)
    manifest = _read_server_manifest(backup_manifest_path(encrypted_path))
    with tempfile.TemporaryDirectory(prefix="solomon-server-restore-", dir=destination.parent) as temporary:
        staged = _decrypt_and_extract_server_archive(encrypted_path, manifest, passphrase, Path(temporary))
        record = _read_server_record(staged)
        _validate_server_record(record, manifest, database_url)
        dump_path = staged / "postgres" / "knowledge.dump"
        restore_postgres(dump_path)
        _verify_staged_journal(staged / "journal")
        for database in sorted((staged / "data").rglob("*.sqlite3")):
            _verify_sqlite_database(database)
        local_root = Path(temporary) / "local-root"
        local_root.mkdir()
        os.replace(staged / "data", local_root / "data")
        os.replace(staged / "journal", local_root / "journal")
        os.replace(local_root, destination)
    AuditJournal(destination / "journal" / "journal.jsonl").append_idempotent(
        "deployment_restore_completed",
        {"deployment_id": record.deployment_id, "archive_sha256": manifest.encrypted_sha256},
        operation_id=record.maintenance_operation_id,
    )
    return ServerRestoreResult(
        destination=str(destination),
        files=plan.files,
        deployment_id=record.deployment_id,
        maintenance_operation_id=record.maintenance_operation_id,
    )


def postgres_dump_runner(database_url: str) -> Callable[[Path], None]:
    """Return a credential-redacting PostgreSQL logical-dump callback."""

    connection = _postgres_client_connection(database_url)

    def dump(destination: Path) -> None:
        executable = shutil.which("pg_dump")
        if executable is None:
            raise BackupError("pg_dump is required for a PostgreSQL backup")
        # The executable is resolved from the fixed pg_dump client name; arguments are not shell-expanded.
        result = subprocess.run(  # noqa: S603  # nosec B603
            [
                executable,
                "--format=custom",
                "--no-owner",
                "--file",
                str(destination),
                *connection.arguments,
            ],
            check=False,
            capture_output=True,
            env=connection.environment,
        )
        if result.returncode != 0:
            raise BackupError("PostgreSQL logical dump failed")

    return dump


def postgres_restore_runner(database_url: str) -> Callable[[Path], None]:
    """Return a restore callback that refuses a non-empty target database."""

    connection = _postgres_client_connection(database_url)

    def restore(dump: Path) -> None:
        if not dump.is_file() or dump.is_symlink():
            raise BackupError("PostgreSQL restore input is unsafe")
        _require_empty_postgres_database(database_url)
        executable = shutil.which("pg_restore")
        if executable is None:
            raise BackupError("pg_restore is required for a PostgreSQL restore")
        # The executable is resolved from the fixed pg_restore client name; arguments are not shell-expanded.
        result = subprocess.run(  # noqa: S603  # nosec B603
            [
                executable,
                "--no-owner",
                "--exit-on-error",
                "--single-transaction",
                "--dbname",
                connection.database_name,
                *connection.connection_arguments,
                str(dump),
            ],
            check=False,
            capture_output=True,
            env=connection.environment,
        )
        if result.returncode != 0:
            raise BackupError("PostgreSQL logical restore failed")

    return restore


@dataclass(frozen=True)
class _PostgresClientConnection:
    database_name: str
    connection_arguments: tuple[str, ...]
    arguments: tuple[str, ...]
    environment: dict[str, str]


def _postgres_client_connection(database_url: str) -> _PostgresClientConnection:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise BackupError("PostgreSQL backup requires an absolute PostgreSQL database URL")
    username = unquote(parsed.username) if parsed.username else None
    if not username:
        raise BackupError("PostgreSQL backup requires a database user")
    database_name = parsed.path.strip("/")
    environment = os.environ.copy()
    if parsed.password is not None:
        environment["PGPASSWORD"] = unquote(parsed.password)
    elif "PGPASSWORD" in environment:
        environment.pop("PGPASSWORD")
    sslmode = parse_qs(parsed.query).get("sslmode", [None])[0]
    if sslmode is not None:
        environment["PGSSLMODE"] = sslmode
    connection_arguments = ("--host", parsed.hostname, "--port", str(parsed.port or 5432), "--username", username)
    return _PostgresClientConnection(
        database_name=database_name,
        connection_arguments=connection_arguments,
        arguments=(*connection_arguments, "--dbname", database_name),
        environment=environment,
    )


def _require_empty_postgres_database(database_url: str) -> None:
    try:
        from solomon.store.postgres.connection import default_connect

        connection = default_connect(database_url)
        try:
            existing = connection.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema <> 'information_schema'
                AND table_schema NOT LIKE 'pg_%'
                AND table_type = 'BASE TABLE'
                LIMIT 1
                """
            ).fetchone()
        finally:
            connection.close()
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError("PostgreSQL restore target cannot be inspected") from exc
    if existing is not None:
        raise BackupError("PostgreSQL restore target must be empty")


def _require_directory(path: Path | str, *, label: str) -> Path:
    directory = Path(path)
    if not directory.is_dir() or directory.is_symlink():
        raise BackupError(f"{label} directory does not exist or is not a directory")
    return directory


def _require_external_backup_destination(target: Path, *active_roots: Path) -> None:
    """Keep backup artifacts outside the source tree to avoid self-inclusion."""

    resolved_target = target.resolve()
    if any(resolved_target.is_relative_to(root.resolve()) for root in active_roots):
        raise BackupError("backup destination must be outside active data and audit directories")


def _require_mixed_metadata(data_dir: Path, database_url: str) -> DeploymentMetadata:
    try:
        metadata = read_metadata(data_dir)
    except DeploymentError as exc:
        raise BackupError(str(exc)) from exc
    if metadata is None:
        raise BackupError("deployment metadata is required before a coordinated server backup")
    if (
        metadata.profile is not DeploymentProfile.MIXED
        or profile_for_database_url(database_url) is not DeploymentProfile.MIXED
    ):
        raise BackupError("coordinated server backup requires the mixed PostgreSQL/SQLite deployment profile")
    return metadata


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    sqlite_consistent: bool,
    excluded_root_names: set[str] | None = None,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if excluded_root_names and relative.parts and relative.parts[0] in excluded_root_names:
            continue
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


def _read_server_manifest(path: Path) -> EncryptedServerBackupManifest:
    try:
        return EncryptedServerBackupManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise BackupError("server backup manifest is missing or invalid") from exc


def _decrypt_and_extract_server_archive(
    encrypted_path: Path,
    manifest: EncryptedServerBackupManifest,
    passphrase: str,
    working_directory: Path,
) -> Path:
    if not encrypted_path.is_file() or encrypted_path.is_symlink():
        raise BackupError("backup archive does not exist or is unsafe")
    if not passphrase:
        raise BackupError("backup passphrase is required")
    decrypted = working_directory / "backup.tar"
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
    staged = working_directory / "staged"
    _extract_archive(
        decrypted,
        staged,
        allowed_roots={"data", "journal", "postgres"},
        allowed_files={SERVER_BACKUP_RECORD_NAME},
    )
    dump_path = staged / "postgres" / "knowledge.dump"
    if not dump_path.is_file() or dump_path.is_symlink() or dump_path.stat().st_size == 0:
        raise BackupError("server backup does not contain a valid PostgreSQL dump")
    return staged


def _read_server_record(staged: Path) -> ServerBackupRecord:
    try:
        return ServerBackupRecord.model_validate_json((staged / SERVER_BACKUP_RECORD_NAME).read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise BackupError("server backup record is missing or invalid") from exc


def _validate_server_record(
    record: ServerBackupRecord,
    manifest: EncryptedServerBackupManifest,
    database_url: str,
) -> None:
    if (
        record.deployment_id != manifest.deployment_id
        or record.maintenance_operation_id != manifest.maintenance_operation_id
    ):
        raise BackupError("server backup record does not match encrypted manifest")
    if _database_logical_identity(record.database_url) != _database_logical_identity(database_url):
        raise BackupError("restore database logical identity does not match the backup plan")


def _database_logical_identity(database_url: str) -> tuple[str, str]:
    """Compare portable database identity while allowing an isolated restore host."""

    parsed = urlparse(database_url)
    database_name = parsed.path.strip("/")
    username = parsed.username or ""
    if parsed.scheme not in {"postgres", "postgresql"} or not database_name or not username:
        raise BackupError("PostgreSQL database identity is invalid")
    return username, database_name


def _write_incomplete_marker(staging: Path, operation_id: str) -> None:
    """Leave a bounded operator-visible marker if a checkpoint cannot complete."""

    try:
        (staging / "INCOMPLETE.json").write_text(
            json.dumps({"schema_id": "solomon.incomplete_backup.v1", "operation_id": operation_id}, sort_keys=True),
            encoding="utf-8",
        )
    except OSError:
        # The primary error is more useful; this marker is diagnostic only.
        pass


def _extract_archive(
    archive_path: Path,
    destination: Path,
    *,
    allowed_roots: set[str] | None = None,
    allowed_files: set[str] | None = None,
) -> BackupArchiveManifest:
    roots = allowed_roots or {"data", "journal"}
    files = allowed_files or set()
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise BackupError("backup archive exceeds the member-count limit")
        if any(member.size > MAX_ARCHIVE_MEMBER_BYTES for member in members):
            raise BackupError("backup archive contains an oversized member")
        if sum(member.size for member in members) > MAX_ARCHIVE_TOTAL_BYTES:
            raise BackupError("backup archive exceeds the total-size limit")
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise BackupError("backup archive contains duplicate paths")
        for member in members:
            _validate_member(member, allowed_roots=roots, allowed_files=files)
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
        _validate_manifest_paths(manifest, allowed_roots=roots, allowed_files=files)
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


def _validate_member(member: tarfile.TarInfo, *, allowed_roots: set[str], allowed_files: set[str]) -> None:
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
        or (member.name not in allowed_files and path.parts[0] not in allowed_roots)
    ):
        raise BackupError(f"unsafe backup archive member: {member.name}")


def _validate_manifest_paths(
    manifest: BackupArchiveManifest,
    *,
    allowed_roots: set[str],
    allowed_files: set[str],
) -> None:
    paths = [file.path for file in manifest.files]
    if len(paths) != len(set(paths)):
        raise BackupError("backup manifest contains duplicate paths")
    for path in paths:
        pure_path = PurePosixPath(path)
        unsafe = pure_path.is_absolute() or ".." in pure_path.parts or not pure_path.parts
        if unsafe or (path not in allowed_files and pure_path.parts[0] not in allowed_roots):
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
