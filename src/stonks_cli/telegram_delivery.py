from __future__ import annotations

import json
import platform
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from stonks_cli.operator import notify_telegram
from stonks_cli.storage import EncryptedLedger

_ALIAS = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SERVICE = "com.stonks-cli.telegram"


class TelegramEventCategory(StrEnum):
    ADVISORY = "advisory"
    POLICY_CONFLICT = "policy_conflict"
    JOB_FAILURE = "job_failure"
    ROUTINE_REPORT = "routine_report"
    RISK_WARNING = "risk_warning"
    JOB_STATUS = "job_status"


class TelegramMessageField(StrEnum):
    INSTRUMENT = "instrument"
    ACTION = "action"
    RATIONALE = "rationale"
    AMOUNTS = "amounts"
    QUANTITIES = "quantities"
    BALANCES = "balances"


_DEFAULT_EVENTS = (
    TelegramEventCategory.ADVISORY,
    TelegramEventCategory.POLICY_CONFLICT,
    TelegramEventCategory.JOB_FAILURE,
)
_DEFAULT_FIELDS = (
    TelegramMessageField.INSTRUMENT,
    TelegramMessageField.ACTION,
    TelegramMessageField.RATIONALE,
)


@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool = False
    recipient_aliases: tuple[str, ...] = ()
    event_categories: tuple[TelegramEventCategory, ...] = _DEFAULT_EVENTS
    message_fields: tuple[TelegramMessageField, ...] = _DEFAULT_FIELDS
    scheduled_enabled: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        aliases = tuple(_normalize_alias(alias) for alias in self.recipient_aliases)
        if len(set(aliases)) != len(aliases):
            raise ValueError("Telegram recipient aliases must be unique")
        if not isinstance(self.enabled, bool) or not isinstance(self.scheduled_enabled, bool):
            raise ValueError("Telegram settings flags must be boolean")
        if self.scheduled_enabled and not self.enabled:
            raise ValueError("scheduled Telegram delivery requires Telegram to be enabled")
        if not self.event_categories or any(
            not isinstance(event, TelegramEventCategory) for event in self.event_categories
        ):
            raise ValueError("Telegram event categories are required")
        if len(set(self.event_categories)) != len(self.event_categories):
            raise ValueError("Telegram event categories must be unique")
        if not self.message_fields or any(
            not isinstance(field, TelegramMessageField) for field in self.message_fields
        ):
            raise ValueError("Telegram message fields are required")
        if len(set(self.message_fields)) != len(self.message_fields):
            raise ValueError("Telegram message fields must be unique")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("Telegram settings version must be a positive integer")
        object.__setattr__(self, "recipient_aliases", aliases)


@dataclass(frozen=True)
class TelegramArtifact:
    artifact_id: str
    event_category: TelegramEventCategory
    instrument: str | None = None
    action: str | None = None
    rationale: str | None = None
    amounts: str | None = None
    quantities: str | None = None
    balances: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_id, str) or not self.artifact_id.strip():
            raise ValueError("Telegram artifact identifier is required")
        if not isinstance(self.event_category, TelegramEventCategory):
            raise ValueError("Telegram artifact event category is invalid")
        if self.action is not None and self.action.strip().lower() not in {"buy", "sell"}:
            raise ValueError("Telegram advisory action must be buy or sell")
        object.__setattr__(self, "artifact_id", self.artifact_id.strip())


@dataclass(frozen=True)
class TelegramDeliveryRecord:
    delivery_id: int
    profile: str
    artifact_id: str
    channel: str
    attempted_at: datetime
    delivered_at: datetime | None
    result: str
    error_classification: str | None


@dataclass(frozen=True)
class TelegramSettingsAudit:
    created_at: datetime
    version: int
    source: str
    recipient_count: int
    scheduled_enabled: bool


def settings(ledger: EncryptedLedger) -> TelegramSettings:
    with ledger.connection() as connection:
        _initialize(connection)
        row = connection.execute("SELECT * FROM telegram_settings WHERE singleton = 1").fetchone()
    return _settings_from_row(row)


def configure(
    ledger: EncryptedLedger,
    *,
    enabled: bool,
    recipient_aliases: tuple[str, ...],
    event_categories: tuple[TelegramEventCategory, ...],
    message_fields: tuple[TelegramMessageField, ...],
    scheduled_enabled: bool,
    source: str = "local",
) -> TelegramSettings:
    previous = settings(ledger)
    candidate = TelegramSettings(
        enabled,
        recipient_aliases,
        event_categories,
        message_fields,
        scheduled_enabled,
        previous.version,
    )
    _assert_configured_aliases(ledger, candidate.recipient_aliases)
    if candidate == previous:
        return previous
    configured = TelegramSettings(
        candidate.enabled,
        candidate.recipient_aliases,
        candidate.event_categories,
        candidate.message_fields,
        candidate.scheduled_enabled,
        previous.version + 1,
    )
    with ledger.connection() as connection:
        _initialize(connection)
        _write_settings(connection, configured)
        connection.execute(
            "INSERT INTO telegram_settings_audit (created_at, version, source, recipient_count, scheduled_enabled) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(UTC).isoformat(),
                configured.version,
                _safe_source(source),
                len(configured.recipient_aliases),
                int(configured.scheduled_enabled),
            ),
        )
    return configured


def add_recipient(
    ledger: EncryptedLedger, alias: str, token: str, chat_id: str, *, source: str = "local"
) -> TelegramSettings:
    alias = _normalize_alias(alias)
    _validate_credential(token, "Telegram token")
    _validate_credential(chat_id, "Telegram recipient")
    current = settings(ledger)
    if alias in _configured_recipient_aliases(ledger):
        raise ValueError("Telegram recipient alias already exists")
    _store_credentials(ledger, alias, token, chat_id)
    aliases = current.recipient_aliases or (alias,)
    return configure(
        ledger,
        enabled=current.enabled,
        recipient_aliases=aliases,
        event_categories=current.event_categories,
        message_fields=current.message_fields,
        scheduled_enabled=current.scheduled_enabled,
        source=source,
    )


def remove_recipient(ledger: EncryptedLedger, alias: str, *, source: str = "local") -> TelegramSettings:
    alias = _normalize_alias(alias)
    current = settings(ledger)
    if alias not in _configured_recipient_aliases(ledger):
        raise ValueError("Telegram recipient alias is unknown")
    _delete_credentials(ledger, alias)
    aliases = tuple(item for item in current.recipient_aliases if item != alias)
    return configure(
        ledger,
        enabled=current.enabled,
        recipient_aliases=aliases,
        event_categories=current.event_categories,
        message_fields=current.message_fields,
        scheduled_enabled=current.scheduled_enabled and bool(aliases),
        source=source,
    )


def deliver(
    ledger: EncryptedLedger,
    artifact: TelegramArtifact,
    *,
    scheduled: bool = False,
    token_override: str | None = None,
    chat_id_override: str | None = None,
    now: datetime | None = None,
) -> tuple[TelegramDeliveryRecord, ...]:
    configured = settings(ledger)
    if not configured.enabled or artifact.event_category not in configured.event_categories:
        return ()
    if scheduled and not configured.scheduled_enabled:
        return ()
    if (token_override is None) != (chat_id_override is None):
        raise ValueError("Telegram environment overrides require token and recipient")
    if scheduled and token_override is not None:
        raise ValueError("scheduled Telegram delivery requires secure stored credentials")
    if token_override is not None:
        _validate_credential(token_override, "Telegram token")
        _validate_credential(chat_id_override, "Telegram recipient")
    elif not configured.recipient_aliases:
        return ()
    attempted_at = (now or datetime.now(UTC)).astimezone(UTC)
    message = _message(artifact, configured.message_fields)
    records = []
    aliases = ("override",) if token_override is not None else configured.recipient_aliases
    for alias in aliases:
        try:
            if token_override is not None:
                assert chat_id_override is not None
                token, chat_id = token_override, chat_id_override
            else:
                token, chat_id = _load_credentials(ledger, alias)
            delivered = notify_telegram(token, chat_id, "stonks-cli", message)
            records.append(
                _record_delivery(
                    ledger,
                    artifact.artifact_id,
                    attempted_at,
                    attempted_at if delivered else None,
                    "delivered" if delivered else "failed",
                    None if delivered else "transport_failure",
                )
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            records.append(
                _record_delivery(
                    ledger,
                    artifact.artifact_id,
                    attempted_at,
                    None,
                    "failed",
                    "credential_unavailable",
                )
            )
    return tuple(records)


def delivery_records(ledger: EncryptedLedger) -> tuple[TelegramDeliveryRecord, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM telegram_delivery_audit ORDER BY delivery_id").fetchall()
    return tuple(
        TelegramDeliveryRecord(
            row["delivery_id"],
            row["profile"],
            row["artifact_id"],
            row["channel"],
            datetime.fromisoformat(row["attempted_at"]),
            None if row["delivered_at"] is None else datetime.fromisoformat(row["delivered_at"]),
            row["result"],
            row["error_classification"],
        )
        for row in rows
    )


def settings_audit(ledger: EncryptedLedger) -> tuple[TelegramSettingsAudit, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM telegram_settings_audit ORDER BY audit_id").fetchall()
    return tuple(
        TelegramSettingsAudit(
            datetime.fromisoformat(row["created_at"]),
            row["version"],
            row["source"],
            row["recipient_count"],
            bool(row["scheduled_enabled"]),
        )
        for row in rows
    )


def _message(artifact: TelegramArtifact, fields: tuple[TelegramMessageField, ...]) -> str:
    values = {
        TelegramMessageField.INSTRUMENT: artifact.instrument,
        TelegramMessageField.ACTION: artifact.action,
        TelegramMessageField.RATIONALE: artifact.rationale,
        TelegramMessageField.AMOUNTS: artifact.amounts,
        TelegramMessageField.QUANTITIES: artifact.quantities,
        TelegramMessageField.BALANCES: artifact.balances,
    }
    return "\n".join(
        value.strip()
        for field, value in values.items()
        if field in fields and isinstance(value, str) and value.strip()
    ) or artifact.event_category.value


def _record_delivery(
    ledger: EncryptedLedger,
    artifact_id: str,
    attempted_at: datetime,
    delivered_at: datetime | None,
    result: str,
    error_classification: str | None,
) -> TelegramDeliveryRecord:
    with ledger.connection() as connection:
        _initialize(connection)
        cursor = connection.execute(
            "INSERT INTO telegram_delivery_audit (profile, artifact_id, channel, attempted_at, delivered_at, result, error_classification) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                ledger.config.name,
                artifact_id,
                "telegram",
                attempted_at.isoformat(),
                None if delivered_at is None else delivered_at.isoformat(),
                result,
                error_classification,
            ),
        )
        assert cursor.lastrowid is not None
        delivery_id = int(cursor.lastrowid)
    return TelegramDeliveryRecord(
        delivery_id,
        ledger.config.name,
        artifact_id,
        "telegram",
        attempted_at,
        delivered_at,
        result,
        error_classification,
    )


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_settings (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            enabled INTEGER NOT NULL,
            recipient_aliases TEXT NOT NULL,
            event_categories TEXT NOT NULL,
            message_fields TEXT NOT NULL,
            scheduled_enabled INTEGER NOT NULL,
            version INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_recipients (
            alias TEXT PRIMARY KEY
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_credentials (
            alias TEXT PRIMARY KEY,
            token TEXT NOT NULL,
            chat_id TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_settings_audit (
            audit_id INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL,
            version INTEGER NOT NULL,
            source TEXT NOT NULL,
            recipient_count INTEGER NOT NULL,
            scheduled_enabled INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS telegram_delivery_audit (
            delivery_id INTEGER PRIMARY KEY,
            profile TEXT NOT NULL,
            artifact_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            delivered_at TEXT,
            result TEXT NOT NULL,
            error_classification TEXT
        )
        """
    )
    if connection.execute("SELECT 1 FROM telegram_settings WHERE singleton = 1").fetchone() is None:
        _write_settings(connection, TelegramSettings())


def _settings_from_row(row: sqlite3.Row) -> TelegramSettings:
    return TelegramSettings(
        bool(row["enabled"]),
        tuple(json.loads(row["recipient_aliases"])),
        tuple(TelegramEventCategory(value) for value in json.loads(row["event_categories"])),
        tuple(TelegramMessageField(value) for value in json.loads(row["message_fields"])),
        bool(row["scheduled_enabled"]),
        int(row["version"]),
    )


def _write_settings(connection: sqlite3.Connection, configured: TelegramSettings) -> None:
    connection.execute(
        """
        INSERT INTO telegram_settings VALUES (1, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            enabled = excluded.enabled,
            recipient_aliases = excluded.recipient_aliases,
            event_categories = excluded.event_categories,
            message_fields = excluded.message_fields,
            scheduled_enabled = excluded.scheduled_enabled,
            version = excluded.version
        """,
        (
            int(configured.enabled),
            json.dumps(configured.recipient_aliases),
            json.dumps(configured.event_categories),
            json.dumps(configured.message_fields),
            int(configured.scheduled_enabled),
            configured.version,
        ),
    )


def _configured_recipient_aliases(ledger: EncryptedLedger) -> tuple[str, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT alias FROM telegram_recipients ORDER BY alias").fetchall()
    return tuple(row["alias"] for row in rows)


def _assert_configured_aliases(ledger: EncryptedLedger, aliases: tuple[str, ...]) -> None:
    available = set(_configured_recipient_aliases(ledger))
    if not set(aliases) <= available:
        raise ValueError("Telegram recipient alias is unknown")


def _store_credentials(ledger: EncryptedLedger, alias: str, token: str, chat_id: str) -> None:
    if platform.system() == "Darwin":
        _keychain_store(ledger.config.name, alias, "token", token)
        _keychain_store(ledger.config.name, alias, "recipient", chat_id)
        with ledger.connection() as connection:
            _initialize(connection)
            connection.execute("INSERT INTO telegram_recipients VALUES (?)", (alias,))
        return
    if platform.system() != "Linux":
        raise ValueError("Telegram secure storage is unavailable on this platform")
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute("INSERT INTO telegram_recipients VALUES (?)", (alias,))
        connection.execute("INSERT INTO telegram_credentials VALUES (?, ?, ?)", (alias, token, chat_id))


def _load_credentials(ledger: EncryptedLedger, alias: str) -> tuple[str, str]:
    if platform.system() == "Darwin":
        return (
            _keychain_load(ledger.config.name, alias, "token"),
            _keychain_load(ledger.config.name, alias, "recipient"),
        )
    if platform.system() != "Linux":
        raise ValueError("Telegram secure storage is unavailable on this platform")
    with ledger.connection() as connection:
        _initialize(connection)
        row = connection.execute("SELECT token, chat_id FROM telegram_credentials WHERE alias = ?", (alias,)).fetchone()
    if row is None:
        raise ValueError("Telegram secure credential is unavailable")
    return row["token"], row["chat_id"]


def _delete_credentials(ledger: EncryptedLedger, alias: str) -> None:
    if platform.system() == "Darwin":
        for kind in ("token", "recipient"):
            subprocess.run(
                ("security", "delete-generic-password", "-s", _SERVICE, "-a", _keychain_account(ledger.config.name, alias, kind)),
                check=False,
                capture_output=True,
            )
    elif platform.system() == "Linux":
        with ledger.connection() as connection:
            _initialize(connection)
            connection.execute("DELETE FROM telegram_credentials WHERE alias = ?", (alias,))
    else:
        raise ValueError("Telegram secure storage is unavailable on this platform")
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute("DELETE FROM telegram_recipients WHERE alias = ?", (alias,))


def _keychain_store(profile: str, alias: str, kind: str, value: str) -> None:
    if shutil.which("security") is None:
        raise ValueError("macOS Keychain is unavailable")
    result = subprocess.run(
        ("security", "add-generic-password", "-U", "-s", _SERVICE, "-a", _keychain_account(profile, alias, kind), "-w", value),
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError("macOS Keychain credential storage failed")


def _keychain_load(profile: str, alias: str, kind: str) -> str:
    if shutil.which("security") is None:
        raise ValueError("macOS Keychain is unavailable")
    result = subprocess.run(
        ("security", "find-generic-password", "-s", _SERVICE, "-a", _keychain_account(profile, alias, kind), "-w"),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not isinstance(result.stdout, str) or not result.stdout.strip():
        raise ValueError("macOS Keychain credential is unavailable")
    return result.stdout.rstrip("\n")


def _keychain_account(profile: str, alias: str, kind: str) -> str:
    return f"{profile}:{alias}:{kind}"


def _normalize_alias(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Telegram recipient alias is invalid")
    alias = value.strip().lower()
    if not _ALIAS.fullmatch(alias):
        raise ValueError("Telegram recipient alias is invalid")
    return alias


def _validate_credential(value: str | None, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(f"{label} is invalid")


def _safe_source(value: str) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "local"
