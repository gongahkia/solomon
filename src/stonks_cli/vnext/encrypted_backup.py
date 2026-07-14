from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory

BACKUP_MAGIC = b"STONKS-CLI-BACKUP-1\n"
BACKUP_KEY_BYTES = 32
BACKUP_NONCE_BYTES = 12
BACKUP_TAG_BYTES = 16
BACKUP_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class EncryptedBackup:
    path: Path
    plaintext_bytes: int
    encrypted_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("encrypted backup path must be absolute")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (self.plaintext_bytes, self.encrypted_bytes)):
            raise ValueError("encrypted backup sizes are invalid")


def generate_backup_key() -> bytes:
    return os.urandom(BACKUP_KEY_BYTES)


def export_encrypted_backup(source: Path, destination: Path, key: bytes) -> EncryptedBackup:
    _validate_source(source)
    _validate_destination(destination)
    _validate_key(key)
    ensure_private_directory(destination.parent)
    nonce = os.urandom(BACKUP_NONCE_BYTES)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(BACKUP_MAGIC)
    temporary = destination.parent / f".{destination.name}.{os.urandom(16).hex()}.tmp"
    plaintext_bytes = 0
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
            output.write(BACKUP_MAGIC)
            output.write(nonce)
            while chunk := input_file.read(BACKUP_CHUNK_BYTES):
                plaintext_bytes += len(chunk)
                output.write(encryptor.update(chunk))
            output.write(encryptor.finalize())
            output.write(encryptor.tag)
            output.flush()
            os.fsync(output.fileno())
        os.link(temporary, destination)
        temporary.unlink()
        _sync_directory(destination.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    enforce_private_file(destination)
    return EncryptedBackup(destination, plaintext_bytes, destination.stat().st_size)


def _validate_source(source: Path) -> None:
    if not isinstance(source, Path) or not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError("encrypted backup source must be an absolute regular file")


def _validate_destination(destination: Path) -> None:
    if not isinstance(destination, Path) or not destination.is_absolute() or destination.is_symlink():
        raise ValueError("encrypted backup destination must be an absolute non-symlink path")
    if destination.exists():
        raise FileExistsError(destination)


def _validate_key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != BACKUP_KEY_BYTES:
        raise ValueError("encrypted backup key must be 32 bytes")


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
