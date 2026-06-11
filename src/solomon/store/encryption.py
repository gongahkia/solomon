# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from solomon.api.schemas import SolomonModel


class EncryptedArtifactManifest(SolomonModel):
    path: str
    salt_b64: str
    kdf: str = "PBKDF2HMAC-SHA256"
    iterations: int = 390000
    encrypted: bool = True


def derive_fernet_key(passphrase: str, *, salt: bytes, iterations: int = 390000) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


class EncryptedArtifactStore:
    """Encrypt portable at-rest artifacts such as snapshots and audit packs."""

    def __init__(self, *, passphrase: str) -> None:
        if not passphrase:
            raise ValueError("passphrase is required")
        self.passphrase = passphrase

    def encrypt_file(self, source: Path | str, destination: Path | str) -> EncryptedArtifactManifest:
        source_path = Path(source)
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        key = derive_fernet_key(self.passphrase, salt=salt)
        encrypted = Fernet(key).encrypt(source_path.read_bytes())
        destination_path.write_bytes(encrypted)
        return EncryptedArtifactManifest(path=str(destination_path), salt_b64=base64.b64encode(salt).decode("ascii"))

    def decrypt_file(
        self,
        encrypted_path: Path | str,
        destination: Path | str,
        *,
        manifest: EncryptedArtifactManifest,
    ) -> Path:
        salt = base64.b64decode(manifest.salt_b64.encode("ascii"))
        key = derive_fernet_key(self.passphrase, salt=salt, iterations=manifest.iterations)
        decrypted = Fernet(key).decrypt(Path(encrypted_path).read_bytes())
        destination_path = Path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(decrypted)
        return destination_path
