# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidTag
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.keywrap import InvalidUnwrap, aes_key_unwrap, aes_key_wrap
from pydantic import Field, SecretStr, ValidationError

from solomon.api.schemas import SolomonModel


class EncryptedArtifactManifest(SolomonModel):
    path: str
    salt_b64: str
    kdf: str = "PBKDF2HMAC-SHA256"
    iterations: int = 390000
    encrypted: bool = True


class ContentEnvelopeError(RuntimeError):
    pass


class ContentEnvelope(SolomonModel):
    schema_id: Literal["solomon.content-envelope.v1"] = "solomon.content-envelope.v1"
    algorithm: Literal["AES-256-GCM+AES-KW"] = "AES-256-GCM+AES-KW"
    key_ref: str = Field(min_length=1, max_length=256)
    ciphertext_b64: str = Field(min_length=1)
    nonce_b64: str = Field(min_length=1)
    wrapped_dek_b64: str = Field(min_length=1)


class ContentEnvelopeCipher:
    """Envelope-encrypt durable text without persisting plaintext key material."""

    def __init__(self, *, key_ref: str, wrapping_key: str | SecretStr) -> None:
        if not key_ref:
            raise ValueError("content encryption key reference is required")
        value = wrapping_key.get_secret_value() if isinstance(wrapping_key, SecretStr) else wrapping_key
        self.key_ref = key_ref
        self._wrapping_key = _decode_aes256_key(value)

    def encrypt(self, plaintext: str, *, associated_data: str) -> dict[str, Any]:
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        ciphertext = AESGCM(data_key).encrypt(nonce, plaintext.encode("utf-8"), associated_data.encode("utf-8"))
        envelope = ContentEnvelope(
            key_ref=self.key_ref,
            ciphertext_b64=_encode(ciphertext),
            nonce_b64=_encode(nonce),
            wrapped_dek_b64=_encode(aes_key_wrap(self._wrapping_key, data_key)),
        )
        return envelope.model_dump(mode="json")

    def decrypt(self, envelope: Mapping[str, Any], *, associated_data: str) -> str:
        try:
            parsed = ContentEnvelope.model_validate(envelope)
        except ValidationError as exc:
            raise ContentEnvelopeError("content envelope is invalid") from exc
        if parsed.key_ref != self.key_ref:
            raise ContentEnvelopeError("content envelope key reference is unavailable")
        try:
            data_key = aes_key_unwrap(self._wrapping_key, _decode(parsed.wrapped_dek_b64))
            plaintext = AESGCM(data_key).decrypt(
                _decode(parsed.nonce_b64),
                _decode(parsed.ciphertext_b64),
                associated_data.encode("utf-8"),
            )
            return plaintext.decode("utf-8")
        except (InvalidTag, InvalidUnwrap, UnicodeDecodeError, ValueError, binascii.Error) as exc:
            raise ContentEnvelopeError("content envelope cannot be decrypted") from exc


def _decode_aes256_key(value: str) -> bytes:
    try:
        key = _decode(value)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("content encryption key must be base64-encoded 32-byte AES-256 key material") from exc
    if len(key) != 32:
        raise ValueError("content encryption key must be base64-encoded 32-byte AES-256 key material")
    return key


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)


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
