from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from stonks_cli.config import ProfileConfig
from stonks_cli.report_export import (
    RecipientPublicKey,
    add_recipient_key,
    export_audits,
    export_report,
    recipient_keyring_path,
    revoke_recipient_key,
)
from stonks_cli.storage import EncryptedLedger, generate_key_file


def _public_key(private_key: X25519PrivateKey) -> str:
    return base64.b64encode(private_key.public_key().public_bytes_raw()).decode()


def _decrypt_export(path: Path, private_key: X25519PrivateKey, identifier: str) -> dict[str, object]:
    envelope = json.loads(path.read_text())
    header = json.dumps(envelope["header"], sort_keys=True, separators=(",", ":")).encode()
    wrapped = next(item for item in envelope["recipient_wrapped_keys"] if item["recipient_key_id"] == identifier)
    wrapping_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=base64.b64decode(wrapped["salt"]),
        info=b"stonks-cli-report-export-recipient-key-v1" + __import__("hashlib").sha256(header).digest(),
    ).derive(private_key.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(wrapped["ephemeral_public_key"]))))
    data_key = AESGCM(wrapping_key).decrypt(
        base64.b64decode(wrapped["nonce"]),
        base64.b64decode(wrapped["ciphertext"]),
        header + identifier.encode(),
    )
    payload = envelope["payload"]
    return json.loads(
        AESGCM(data_key).decrypt(
            base64.b64decode(payload["nonce"]), base64.b64decode(payload["ciphertext"]), header
        )
    )


def test_report_export_uses_a_new_authenticated_key_for_each_named_recipient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    profile_key = tmp_path / "profile.key"
    generate_key_file(profile_key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(profile_key)))
    primary = X25519PrivateKey.generate()
    recovery = X25519PrivateKey.generate()
    add_recipient_key(RecipientPublicKey("analyst", _public_key(primary)))
    add_recipient_key(RecipientPublicKey("recovery", _public_key(recovery), recovery=True))
    report = {"portfolio": {"secret_balance": "100"}}
    provenance = {"source_hashes": ["a" * 64], "report_kind": "portfolio"}

    first = export_report(
        ledger,
        report,
        tmp_path / "first.stonks",
        ("analyst",),
        provenance=provenance,
        recovery_recipient="recovery",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    second = export_report(
        ledger,
        report,
        tmp_path / "second.stonks",
        ("analyst",),
        provenance=provenance,
        recovery_recipient="recovery",
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    ciphertext = (tmp_path / "first.stonks").read_bytes()
    assert b"secret_balance" not in ciphertext
    assert (tmp_path / "first.stonks").stat().st_mode & 0o077 == 0
    assert _decrypt_export(tmp_path / "first.stonks", primary, "analyst") == report
    assert _decrypt_export(tmp_path / "first.stonks", recovery, "recovery") == report
    assert ciphertext != (tmp_path / "second.stonks").read_bytes()
    assert first.integrity_status == "authenticated"
    assert first.recipient_identifiers == ("analyst", "recovery")
    assert len(export_audits(ledger)) == 2
    assert recipient_keyring_path().read_bytes().find(primary.private_bytes_raw()) == -1
    assert first.export_id != second.export_id


def test_report_export_fails_closed_for_empty_unknown_or_revoked_recipients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "profile.key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    recipient = X25519PrivateKey.generate()
    add_recipient_key(RecipientPublicKey("recipient", _public_key(recipient)))

    with pytest.raises(ValueError, match="explicit recipient"):
        export_report(ledger, {}, tmp_path / "empty", (), provenance={})
    with pytest.raises(ValueError, match="unknown"):
        export_report(ledger, {}, tmp_path / "unknown", ("unknown",), provenance={})
    revoke_recipient_key("recipient")
    with pytest.raises(ValueError, match="revoked"):
        export_report(ledger, {}, tmp_path / "revoked", ("recipient",), provenance={})
