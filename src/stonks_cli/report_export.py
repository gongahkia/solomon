from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from stonks_cli.config import app_root
from stonks_cli.storage import EncryptedLedger, atomic_write

_KEY_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_FORMAT = "stonks-cli-report-export"
_VERSION = 1
_NONCE_SIZE = 12
_DATA_KEY_SIZE = 32
_SALT_SIZE = 16


@dataclass(frozen=True)
class RecipientPublicKey:
    identifier: str
    public_key: str
    revoked: bool = False
    recovery: bool = False

    def __post_init__(self) -> None:
        identifier = self.identifier.strip().lower()
        if not _KEY_IDENTIFIER.fullmatch(identifier):
            raise ValueError("recipient key identifier is invalid")
        if not isinstance(self.revoked, bool) or not isinstance(self.recovery, bool):
            raise ValueError("recipient key flags must be boolean")
        raw = _decode_public_key(self.public_key)
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "public_key", base64.b64encode(raw).decode("ascii"))

    @property
    def raw_public_key(self) -> bytes:
        return _decode_public_key(self.public_key)


@dataclass(frozen=True)
class ExportAudit:
    export_id: str
    created_at: datetime
    envelope_hash: str
    recipient_identifiers: tuple[str, ...]
    provenance: dict[str, object]
    integrity_status: str


def recipient_keyring_path() -> Path:
    return app_root() / "recipient-keyring.json"


def load_recipient_keyring() -> tuple[RecipientPublicKey, ...]:
    path = recipient_keyring_path()
    if not path.exists():
        return ()
    try:
        value = json.loads(path.read_text())
        if value.get("format") != "stonks-cli-recipient-keyring" or value.get("version") != 1:
            raise ValueError("recipient keyring format is unsupported")
        keys = tuple(RecipientPublicKey(**item) for item in value["recipients"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("recipient keyring is invalid") from error
    if len({key.identifier for key in keys}) != len(keys):
        raise ValueError("recipient keyring identifiers must be unique")
    return tuple(sorted(keys, key=lambda key: key.identifier))


def add_recipient_key(key: RecipientPublicKey) -> RecipientPublicKey:
    keys = load_recipient_keyring()
    if any(existing.identifier == key.identifier for existing in keys):
        raise ValueError("recipient key identifier already exists")
    _save_recipient_keyring((*keys, key))
    return key


def revoke_recipient_key(identifier: str) -> RecipientPublicKey:
    normalized = _normalize_identifier(identifier)
    keys = list(load_recipient_keyring())
    for index, key in enumerate(keys):
        if key.identifier == normalized:
            if key.revoked:
                return key
            revoked = RecipientPublicKey(key.identifier, key.public_key, revoked=True, recovery=key.recovery)
            keys[index] = revoked
            _save_recipient_keyring(tuple(keys))
            return revoked
    raise ValueError("recipient key is unknown")


def export_report(
    ledger: EncryptedLedger,
    report: Mapping[str, object],
    destination: Path,
    recipient_identifiers: tuple[str, ...],
    *,
    provenance: Mapping[str, object],
    recovery_recipient: str | None = None,
    created_at: datetime | None = None,
) -> ExportAudit:
    recipients = _resolve_recipients(recipient_identifiers, recovery_recipient)
    if created_at is not None and created_at.tzinfo is None:
        raise ValueError("export time must be timezone-aware")
    moment = (created_at or datetime.now(UTC)).astimezone(UTC)
    report_bytes = _canonical_json(report)
    export_id = uuid4().hex
    recipient_ids = tuple(recipient.identifier for recipient in recipients)
    header: dict[str, object] = {
        "format": _FORMAT,
        "version": _VERSION,
        "export_id": export_id,
        "created_at": moment.isoformat(),
        "provenance": dict(provenance),
        "recipient_key_ids": list(recipient_ids),
    }
    header_bytes = _canonical_json(header)
    data_key = os.urandom(_DATA_KEY_SIZE)
    payload_nonce = os.urandom(_NONCE_SIZE)
    payload = AESGCM(data_key).encrypt(payload_nonce, report_bytes, header_bytes)
    wrapped_keys = [_wrap_data_key(data_key, header_bytes, recipient) for recipient in recipients]
    envelope = {
        "header": header,
        "payload": {
            "algorithm": "AES-256-GCM",
            "nonce": _encode(payload_nonce),
            "ciphertext": _encode(payload),
        },
        "recipient_wrapped_keys": wrapped_keys,
        "integrity": {"status": "authenticated", "algorithm": "AES-256-GCM"},
    }
    ciphertext = _canonical_json(envelope)
    destination = destination.expanduser().resolve()
    if destination.exists():
        raise ValueError("export destination already exists")
    atomic_write(destination, ciphertext)
    audit = ExportAudit(
        export_id,
        moment,
        hashlib.sha256(ciphertext).hexdigest(),
        recipient_ids,
        dict(provenance),
        "authenticated",
    )
    try:
        _record_export_audit(ledger, audit)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return audit


def export_audits(ledger: EncryptedLedger) -> tuple[ExportAudit, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute("SELECT * FROM report_export_audit ORDER BY created_at, export_id").fetchall()
    return tuple(
        ExportAudit(
            row["export_id"],
            datetime.fromisoformat(row["created_at"]),
            row["envelope_hash"],
            tuple(json.loads(row["recipient_identifiers"])),
            json.loads(row["provenance"]),
            row["integrity_status"],
        )
        for row in rows
    )


def _resolve_recipients(
    recipient_identifiers: tuple[str, ...], recovery_recipient: str | None
) -> tuple[RecipientPublicKey, ...]:
    if not recipient_identifiers:
        raise ValueError("at least one explicit recipient is required")
    requested = tuple(_normalize_identifier(identifier) for identifier in recipient_identifiers)
    if len(set(requested)) != len(requested):
        raise ValueError("export recipients must be unique")
    keyring = {key.identifier: key for key in load_recipient_keyring()}
    recipients = []
    for identifier in requested:
        try:
            key = keyring[identifier]
        except KeyError as error:
            raise ValueError("export recipient is unknown") from error
        if key.revoked:
            raise ValueError("export recipient is revoked")
        recipients.append(key)
    if recovery_recipient is not None:
        identifier = _normalize_identifier(recovery_recipient)
        if identifier in requested:
            raise ValueError("recovery recipient must be separately named")
        try:
            recovery = keyring[identifier]
        except KeyError as error:
            raise ValueError("recovery recipient is unknown") from error
        if recovery.revoked or not recovery.recovery:
            raise ValueError("recovery recipient is unavailable")
        recipients.append(recovery)
    return tuple(sorted(recipients, key=lambda key: key.identifier))


def _wrap_data_key(data_key: bytes, header: bytes, recipient: RecipientPublicKey) -> dict[str, str]:
    ephemeral = X25519PrivateKey.generate()
    salt = os.urandom(_SALT_SIZE)
    wrapping_key = HKDF(
        algorithm=hashes.SHA256(),
        length=_DATA_KEY_SIZE,
        salt=salt,
        info=b"stonks-cli-report-export-recipient-key-v1" + hashlib.sha256(header).digest(),
    ).derive(ephemeral.exchange(X25519PublicKey.from_public_bytes(recipient.raw_public_key)))
    nonce = os.urandom(_NONCE_SIZE)
    wrapped = AESGCM(wrapping_key).encrypt(nonce, data_key, header + recipient.identifier.encode())
    return {
        "recipient_key_id": recipient.identifier,
        "ephemeral_public_key": _encode(ephemeral.public_key().public_bytes_raw()),
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "ciphertext": _encode(wrapped),
    }


def _record_export_audit(ledger: EncryptedLedger, audit: ExportAudit) -> None:
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO report_export_audit VALUES (?, ?, ?, ?, ?, ?)",
            (
                audit.export_id,
                audit.created_at.isoformat(),
                audit.envelope_hash,
                json.dumps(audit.recipient_identifiers),
                json.dumps(audit.provenance, sort_keys=True, separators=(",", ":")),
                audit.integrity_status,
            ),
        )


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS report_export_audit (
            export_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            envelope_hash TEXT NOT NULL,
            recipient_identifiers TEXT NOT NULL,
            provenance TEXT NOT NULL,
            integrity_status TEXT NOT NULL
        )
        """
    )


def _save_recipient_keyring(keys: tuple[RecipientPublicKey, ...]) -> None:
    path = recipient_keyring_path()
    payload = {
        "format": "stonks-cli-recipient-keyring",
        "version": 1,
        "recipients": [asdict(key) for key in sorted(keys, key=lambda key: key.identifier)],
    }
    atomic_write(path, _canonical_json(payload))


def _decode_public_key(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("recipient public key is invalid")
    try:
        raw = base64.b64decode(value, validate=True)
        X25519PublicKey.from_public_bytes(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("recipient public key is invalid") from error
    return raw


def _normalize_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("recipient key identifier is invalid")
    identifier = value.strip().lower()
    if not _KEY_IDENTIFIER.fullmatch(identifier):
        raise ValueError("recipient key identifier is invalid")
    return identifier


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    except (TypeError, ValueError) as error:
        raise ValueError("export data must be JSON-compatible") from error


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")
