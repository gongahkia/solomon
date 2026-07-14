from __future__ import annotations

import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from stonks_cli.vnext.encrypted_backup import (
    BACKUP_MAGIC,
    BACKUP_NONCE_BYTES,
    BACKUP_TAG_BYTES,
    export_encrypted_backup,
    generate_backup_key,
)


def test_encrypted_backup_exports_private_authenticated_ciphertext(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "backups" / "source.backup"
    plaintext = b"private SQLite backup\x00row-1\n"
    source.write_bytes(plaintext)
    key = generate_backup_key()

    backup = export_encrypted_backup(source, destination, key)

    encrypted = destination.read_bytes()
    assert backup.path == destination
    assert backup.plaintext_bytes == len(plaintext)
    assert plaintext not in encrypted
    assert _decrypt(encrypted, key) == plaintext
    assert destination.stat().st_mode & 0o777 == 0o600
    tampered = encrypted[:-1] + bytes([encrypted[-1] ^ 1])
    with pytest.raises(InvalidTag):
        _decrypt(tampered, key)


def test_encrypted_backup_fails_closed_for_invalid_key_or_existing_destination(tmp_path):
    source = tmp_path / "source.sqlite3"
    destination = tmp_path / "backup"
    source.write_bytes(b"private")
    destination.write_bytes(b"existing")

    with pytest.raises(ValueError, match="32 bytes"):
        export_encrypted_backup(source, tmp_path / "invalid-key.backup", b"short")
    with pytest.raises(FileExistsError):
        export_encrypted_backup(source, destination, b"k" * 32)
    assert destination.read_bytes() == b"existing"


def _decrypt(encrypted: bytes, key: bytes) -> bytes:
    assert encrypted.startswith(BACKUP_MAGIC)
    nonce_start = len(BACKUP_MAGIC)
    nonce_end = nonce_start + BACKUP_NONCE_BYTES
    nonce = encrypted[nonce_start:nonce_end]
    ciphertext = encrypted[nonce_end:-BACKUP_TAG_BYTES]
    tag = encrypted[-BACKUP_TAG_BYTES:]
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(BACKUP_MAGIC)
    return decryptor.update(ciphertext) + decryptor.finalize()
