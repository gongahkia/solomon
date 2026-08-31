# SPDX-License-Identifier: Apache-2.0

"""Small, local deployment-control primitives for Solomon's durable layout."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from enum import Enum
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from pydantic import Field, ValidationError

from solomon import __version__
from solomon.api.schemas import SolomonModel
from solomon.audit.journal import AuditJournal
from solomon.currency.models import now_utc

DEPLOYMENT_METADATA_NAME = "deployment.json"
MAINTENANCE_STATE_NAME = ".solomon-maintenance.json"
MAINTENANCE_LOCK_NAME = ".solomon-maintenance.lock"
LAYOUT_VERSION: Literal[1] = 1


class DeploymentError(RuntimeError):
    """Raised for a deployment operation that cannot proceed safely."""


class DeploymentProfile(str, Enum):
    SQLITE = "sqlite-only"
    MIXED = "mixed-postgresql-sqlite"


class CheckStatus(str, Enum):
    READY = "ready"
    WARNING = "warning"
    BLOCKED = "blocked"
    NOT_INITIALIZED = "not_initialized"


class DeploymentCheck(SolomonModel):
    component: str = Field(min_length=1)
    status: CheckStatus
    detail: str = Field(min_length=1)


class DeploymentMetadata(SolomonModel):
    schema_id: Literal["solomon.deployment.v1"] = "solomon.deployment.v1"
    layout_version: Literal[1] = LAYOUT_VERSION
    deployment_id: str = Field(min_length=1)
    profile: DeploymentProfile
    created_at: datetime
    initialized_by_version: str = Field(min_length=1)
    components: tuple[str, ...]


class MaintenanceRecord(SolomonModel):
    schema_id: Literal["solomon.maintenance.v1"] = "solomon.maintenance.v1"
    operation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=200)
    created_at: datetime
    owner: str = Field(min_length=1, max_length=200)


class DeploymentPreflightReport(SolomonModel):
    schema_id: Literal["solomon.deployment_preflight.v1"] = "solomon.deployment_preflight.v1"
    profile: DeploymentProfile
    ready: bool
    initialized: bool
    app_version: str
    database_url: str
    checks: list[DeploymentCheck]


class DeploymentCompatibilityReport(SolomonModel):
    schema_id: Literal["solomon.deployment_compatibility.v1"] = "solomon.deployment_compatibility.v1"
    profile: DeploymentProfile
    compatible_for_startup: bool
    writable: bool
    rollback_supported: bool
    detail: str
    metadata: DeploymentMetadata | None = None


class DeploymentUpgradePreflightReport(SolomonModel):
    """Read-only admission result for a controlled, forward-only upgrade."""

    schema_id: Literal["solomon.deployment_upgrade_preflight.v1"] = "solomon.deployment_upgrade_preflight.v1"
    ready: bool
    profile: DeploymentProfile
    preflight: DeploymentPreflightReport
    compatibility: DeploymentCompatibilityReport
    rollback_strategy: Literal["restore-verified-pre-upgrade-backup"] = "restore-verified-pre-upgrade-backup"
    detail: str


def profile_for_database_url(database_url: str) -> DeploymentProfile:
    return (
        DeploymentProfile.MIXED
        if urlparse(database_url).scheme in {"postgres", "postgresql"}
        else DeploymentProfile.SQLITE
    )


def redact_database_url(database_url: str) -> str:
    """Keep connection topology observable without exposing credentials."""

    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return database_url
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    user = f"{parsed.username}@" if parsed.username else ""
    return urlunparse((parsed.scheme, f"{user}{host}", parsed.path, "", "", ""))


def required_components(profile: DeploymentProfile) -> tuple[str, ...]:
    local = (
        "documents-sqlite",
        "authority-sources-sqlite",
        "authority-identifiers-sqlite",
        "workflow-sqlite",
        "retention-registry-json",
        "tenant-registry-json",
        "audit-journal-jsonl",
    )
    if profile is DeploymentProfile.MIXED:
        return ("postgresql-knowledge-graph-retrieval-operations", *local)
    return ("sqlite-knowledge-graph-retrieval-operations", *local)


def metadata_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / DEPLOYMENT_METADATA_NAME


def read_metadata(data_dir: Path | str) -> DeploymentMetadata | None:
    path = metadata_path(data_dir)
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise DeploymentError("deployment metadata path is unsafe")
    try:
        return DeploymentMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise DeploymentError("deployment metadata is invalid") from exc


def initialize_deployment(
    *,
    data_dir: Path | str,
    journal_dir: Path | str,
    database_url: str,
    owner: str = "cli",
) -> tuple[DeploymentMetadata, bool]:
    """Create the durable deployment marker once; repeated calls are read-only."""

    data = _ensure_private_directory(data_dir, label="data")
    journal = _ensure_private_directory(journal_dir, label="journal")
    profile = profile_for_database_url(database_url)
    gate = MaintenanceGate(data)
    # Bootstrap needs serialization but does not claim a long-lived maintenance
    # interval: service processes are not started until Compose observes this
    # one-shot command complete.
    with gate._exclusive_lock():
        existing = read_metadata(data)
        if existing is not None:
            if existing.profile is not profile:
                raise DeploymentError("deployment metadata profile does not match configured database backend")
            return existing, False
        metadata = DeploymentMetadata(
            deployment_id=str(uuid4()),
            profile=profile,
            created_at=now_utc(),
            initialized_by_version=__version__,
            components=required_components(profile),
        )
        _write_new_json(metadata_path(data), metadata.model_dump(mode="json"))
        AuditJournal(journal / "journal.jsonl").append_idempotent(
            "deployment_initialized",
            {
                "deployment_id": metadata.deployment_id,
                "profile": metadata.profile.value,
                "layout_version": metadata.layout_version,
                "owner": owner,
            },
            operation_id=f"deployment-initialized:{metadata.deployment_id}",
        )
        return metadata, True


def deployment_preflight(
    *,
    data_dir: Path | str,
    journal_dir: Path | str,
    database_url: str,
    require_initialized: bool = False,
) -> DeploymentPreflightReport:
    """Inspect prerequisites without creating stores or applying migrations."""

    data = Path(data_dir)
    journal = Path(journal_dir)
    profile = profile_for_database_url(database_url)
    checks = [_directory_check(data, "local-data"), _directory_check(journal, "audit-journal")]
    metadata = read_metadata(data) if data.exists() else None
    if metadata is None:
        checks.append(
            DeploymentCheck(
                component="deployment-metadata",
                status=CheckStatus.NOT_INITIALIZED,
                detail="run deployment init before production backup, restore, or upgrade",
            )
        )
    elif metadata.profile is not profile:
        checks.append(
            DeploymentCheck(
                component="deployment-metadata",
                status=CheckStatus.BLOCKED,
                detail="recorded profile does not match configured database backend",
            )
        )
    else:
        checks.append(
            DeploymentCheck(
                component="deployment-metadata",
                status=CheckStatus.READY,
                detail="layout metadata is valid",
            )
        )
    checks.append(_journal_check(journal))
    checks.append(
        _postgres_check(database_url) if profile is DeploymentProfile.MIXED else _sqlite_knowledge_check(data)
    )
    blocked = any(check.status is CheckStatus.BLOCKED for check in checks)
    uninitialized = any(check.status is CheckStatus.NOT_INITIALIZED for check in checks)
    return DeploymentPreflightReport(
        profile=profile,
        ready=not blocked and (not require_initialized or not uninitialized),
        initialized=metadata is not None,
        app_version=__version__,
        database_url=redact_database_url(database_url),
        checks=checks,
    )


def compatibility_report(*, data_dir: Path | str, database_url: str) -> DeploymentCompatibilityReport:
    metadata = read_metadata(data_dir)
    profile = profile_for_database_url(database_url)
    if metadata is None:
        return DeploymentCompatibilityReport(
            profile=profile,
            compatible_for_startup=True,
            writable=True,
            rollback_supported=False,
            detail="legacy deployment has no layout marker; initialize and take a verified backup before upgrade",
        )
    if metadata.profile is not profile:
        return DeploymentCompatibilityReport(
            profile=profile,
            compatible_for_startup=False,
            writable=False,
            rollback_supported=False,
            detail="configured backend differs from immutable deployment layout marker",
            metadata=metadata,
        )
    return DeploymentCompatibilityReport(
        profile=profile,
        compatible_for_startup=True,
        writable=True,
        rollback_supported=False,
        detail="this application can read and write the recorded layout; database downgrade is restore-only",
        metadata=metadata,
    )


def upgrade_preflight(
    *, data_dir: Path | str, journal_dir: Path | str, database_url: str
) -> DeploymentUpgradePreflightReport:
    """Check current prerequisites without migrating or creating state."""

    preflight = deployment_preflight(
        data_dir=data_dir,
        journal_dir=journal_dir,
        database_url=database_url,
        require_initialized=True,
    )
    compatibility = compatibility_report(data_dir=data_dir, database_url=database_url)
    ready = preflight.ready and compatibility.compatible_for_startup and compatibility.writable
    return DeploymentUpgradePreflightReport(
        ready=ready,
        profile=preflight.profile,
        preflight=preflight,
        compatibility=compatibility,
        detail=(
            "take and inspect a coordinated backup before forward migration; rollback is a verified restore"
            if ready
            else "resolve blocked or uninitialized prerequisites before an upgrade"
        ),
    )


class MaintenanceGate:
    """Durable fail-closed maintenance state shared through the data volume."""

    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self._state_path = self.data_dir / MAINTENANCE_STATE_NAME
        self._lock_path = self.data_dir / MAINTENANCE_LOCK_NAME

    def active(self) -> MaintenanceRecord | None:
        if not self._state_path.exists():
            return None
        if not self._state_path.is_file() or self._state_path.is_symlink():
            raise DeploymentError("maintenance state path is unsafe")
        try:
            return MaintenanceRecord.model_validate_json(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise DeploymentError("maintenance state is invalid; operator intervention is required") from exc

    def acquire(self, *, reason: str, owner: str) -> MaintenanceRecord:
        if not self.data_dir.is_dir() or self.data_dir.is_symlink():
            raise DeploymentError("data directory must exist before maintenance can begin")
        with self._exclusive_lock():
            active = self.active()
            if active is not None:
                raise DeploymentError("deployment is already in maintenance; inspect it before another operation")
            record = MaintenanceRecord(operation_id=str(uuid4()), reason=reason, owner=owner, created_at=now_utc())
            _atomic_write_json(self._state_path, record.model_dump(mode="json"))
            return record

    def release(self, operation_id: str) -> None:
        with self._exclusive_lock():
            active = self.active()
            if active is None:
                return
            if active.operation_id != operation_id:
                raise DeploymentError("maintenance state is owned by a different operation")
            self._state_path.unlink()

    def _exclusive_lock(self) -> Any:
        self._lock_path.touch(mode=0o600, exist_ok=True)
        lock_file = self._lock_path.open("r+", encoding="utf-8")

        class _LockContext:
            def __enter__(self_nonlocal: object) -> None:
                flock(lock_file.fileno(), LOCK_EX)

            def __exit__(self_nonlocal: object, exc_type: object, exc: object, tb: object) -> None:
                flock(lock_file.fileno(), LOCK_UN)
                lock_file.close()

        return _LockContext()


def _ensure_private_directory(path: Path | str, *, label: str) -> Path:
    directory = Path(path)
    if directory.exists() and (not directory.is_dir() or directory.is_symlink()):
        raise DeploymentError(f"{label} directory path is unsafe")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        directory.chmod(0o700)
    except OSError as exc:
        raise DeploymentError(f"{label} directory permissions cannot be restricted") from exc
    return directory


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as destination:
            os.chmod(path, 0o600)
            destination.write(json.dumps(value, sort_keys=True, indent=2))
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
    except FileExistsError as exc:
        raise DeploymentError("deployment metadata already exists") from exc


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as tmp:
        tmp.write(json.dumps(value, sort_keys=True, indent=2))
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        temporary_path = Path(tmp.name)
    try:
        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _directory_check(path: Path, component: str) -> DeploymentCheck:
    if not path.exists():
        return DeploymentCheck(
            component=component,
            status=CheckStatus.NOT_INITIALIZED,
            detail="directory does not exist",
        )
    if not path.is_dir() or path.is_symlink():
        return DeploymentCheck(
            component=component,
            status=CheckStatus.BLOCKED,
            detail="path is not a safe directory",
        )
    if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
        return DeploymentCheck(
            component=component,
            status=CheckStatus.BLOCKED,
            detail="directory is not readable and writable",
        )
    return DeploymentCheck(component=component, status=CheckStatus.READY, detail="directory is accessible")


def _journal_check(journal_dir: Path) -> DeploymentCheck:
    if not journal_dir.is_dir():
        return DeploymentCheck(
            component="audit-chain",
            status=CheckStatus.NOT_INITIALIZED,
            detail="journal directory is absent",
        )
    journal_path = journal_dir / "journal.jsonl"
    if not journal_path.exists():
        return DeploymentCheck(
            component="audit-chain",
            status=CheckStatus.NOT_INITIALIZED,
            detail="journal has not been created",
        )
    verification = AuditJournal(journal_path).verify()
    if not verification.ok:
        return DeploymentCheck(
            component="audit-chain", status=CheckStatus.BLOCKED, detail="audit hash chain is invalid"
        )
    return DeploymentCheck(component="audit-chain", status=CheckStatus.READY, detail="audit hash chain verifies")


def _sqlite_knowledge_check(data_dir: Path) -> DeploymentCheck:
    path = data_dir / "solomon.sqlite3"
    if not path.exists():
        return DeploymentCheck(
            component="knowledge-store",
            status=CheckStatus.NOT_INITIALIZED,
            detail="SQLite knowledge database is absent",
        )
    if not path.is_file() or path.is_symlink():
        return DeploymentCheck(
            component="knowledge-store", status=CheckStatus.BLOCKED, detail="SQLite knowledge path is unsafe"
        )
    return DeploymentCheck(
        component="knowledge-store", status=CheckStatus.READY, detail="SQLite knowledge database is present"
    )


def _postgres_check(database_url: str) -> DeploymentCheck:
    try:
        from solomon.store.postgres.connection import default_connect

        connection = default_connect(database_url)
        try:
            extension = connection.execute("SELECT 1 FROM pg_extension WHERE extname = %s", ("vector",)).fetchone()
            if extension is None:
                return DeploymentCheck(
                    component="postgresql-pgvector",
                    status=CheckStatus.BLOCKED,
                    detail="pgvector extension is unavailable",
                )
        finally:
            connection.close()
    except Exception:
        return DeploymentCheck(
            component="postgresql-pgvector",
            status=CheckStatus.BLOCKED,
            detail="PostgreSQL or pgvector cannot be reached",
        )
    return DeploymentCheck(
        component="postgresql-pgvector",
        status=CheckStatus.READY,
        detail="PostgreSQL and pgvector are reachable",
    )


__all__ = [
    "CheckStatus", "DeploymentCheck", "DeploymentCompatibilityReport", "DeploymentError", "DeploymentMetadata",
    "DeploymentPreflightReport", "DeploymentProfile", "DeploymentUpgradePreflightReport", "MaintenanceGate",
    "MaintenanceRecord", "compatibility_report", "deployment_preflight", "initialize_deployment", "metadata_path",
    "profile_for_database_url", "read_metadata", "upgrade_preflight",
    "redact_database_url", "required_components",
]
