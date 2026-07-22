from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import stat
import tempfile
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from stonks_cli.config import LLMSettings, ProfileConfig, profile_dir, save_profile
from stonks_cli.errors import EncryptedStorageError, KeyFileError

_MAGIC_PREFIX = b"STONKS"
_FORMAT_VERSION = 1
_VERSION_SIZE = 2
_MAGIC = _MAGIC_PREFIX + _FORMAT_VERSION.to_bytes(_VERSION_SIZE, "little")
_NONCE_SIZE = 12
_KEY_SIZE = 32
MigrationFunction = Callable[[bytes, bytes, str, str], bytes]


def _envelope_version(payload: bytes) -> int:
    if len(payload) < len(_MAGIC) or not payload.startswith(_MAGIC_PREFIX):
        raise EncryptedStorageError("invalid encrypted storage envelope")
    return int.from_bytes(payload[len(_MAGIC_PREFIX) : len(_MAGIC)], "little")


@dataclass(frozen=True)
class EncryptedStorageMigration:
    version: int
    name: str
    apply: MigrationFunction

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 2:
            raise ValueError("encrypted storage migration version must be an integer of at least 2")
        if not isinstance(self.name, str) or not self.name or not callable(self.apply):
            raise ValueError("encrypted storage migration name and apply function are required")


@dataclass(frozen=True)
class EncryptedStorageMigrationRegistry:
    migrations: tuple[EncryptedStorageMigration, ...] = ()

    def __post_init__(self) -> None:
        versions = tuple(migration.version for migration in self.migrations)
        if versions != tuple(range(2, len(self.migrations) + 2)):
            raise ValueError("encrypted storage migration versions must be contiguous and ordered")
        if len({migration.name for migration in self.migrations}) != len(self.migrations):
            raise ValueError("encrypted storage migration names must be unique")

    @property
    def latest_version(self) -> int:
        return len(self.migrations) + 1

    def migrate(self, payload: bytes, key: bytes, profile: str, label: str) -> bytes:
        version = _envelope_version(payload)
        if version < 1 or version > self.latest_version:
            raise EncryptedStorageError(f"unsupported encrypted storage format version:{version}")
        while version < self.latest_version:
            migration = self.migrations[version - 1]
            payload = migration.apply(payload, key, profile, label)
            migrated_version = _envelope_version(payload)
            if migrated_version != migration.version:
                raise EncryptedStorageError(
                    "encrypted storage migration produced an invalid version"
                )
            version = migrated_version
        return payload


_MIGRATIONS = EncryptedStorageMigrationRegistry()


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def generate_key_file(path: Path) -> None:
    path = path.expanduser().resolve()
    _private_directory(path.parent)
    if path.exists():
        raise KeyFileError("key file already exists")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, secrets.token_bytes(_KEY_SIZE))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_key_file(path: Path) -> bytes:
    path = path.expanduser().resolve()
    try:
        info = path.stat()
    except FileNotFoundError as error:
        raise KeyFileError("key file not found") from error
    if not stat.S_ISREG(info.st_mode) or info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise KeyFileError("key file must be a private regular file")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise KeyFileError("key file owner does not match current user")
    key = path.read_bytes()
    if len(key) != _KEY_SIZE:
        raise KeyFileError("key file must contain exactly 32 raw bytes")
    return key


def _aad(profile: str, label: str) -> bytes:
    return f"stonks-cli:{profile}:{label}:v1".encode()


def encrypt(key: bytes, plaintext: bytes, *, profile: str, label: str) -> bytes:
    nonce = secrets.token_bytes(_NONCE_SIZE)
    return _MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, _aad(profile, label))


def decrypt(key: bytes, payload: bytes, *, profile: str, label: str) -> bytes:
    payload = _MIGRATIONS.migrate(payload, key, profile, label)
    if len(payload) < len(_MAGIC) + _NONCE_SIZE + 16 or not payload.startswith(_MAGIC):
        raise EncryptedStorageError("invalid encrypted storage envelope")
    nonce = payload[len(_MAGIC) : len(_MAGIC) + _NONCE_SIZE]
    try:
        return AESGCM(key).decrypt(
            nonce, payload[len(_MAGIC) + _NONCE_SIZE :], _aad(profile, label)
        )
    except Exception as error:
        raise EncryptedStorageError("encrypted storage authentication failed") from error


def atomic_write(path: Path, data: bytes) -> None:
    _private_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class EncryptedLedger:
    def __init__(self, config: ProfileConfig) -> None:
        self.config = config
        self.root = profile_dir(config.name)
        self.path = self.root / "ledger.sqlite.enc"
        self.sources = self.root / "sources"

    @property
    def key(self) -> bytes:
        return read_key_file(Path(self.config.key_file))

    def archive_source(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        path = self.sources / f"{digest}.enc"
        if not path.exists():
            atomic_write(
                path, encrypt(self.key, content, profile=self.config.name, label=f"source:{digest}")
            )
        return digest

    def archived_source_hashes(self) -> tuple[str, ...]:
        if not self.sources.is_dir():
            return ()
        return tuple(
            path.stem
            for path in sorted(self.sources.glob("*.enc"))
            if len(path.stem) == 64 and all(character in "0123456789abcdef" for character in path.stem)
        )

    def _load(self) -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        if self.path.exists():
            plaintext = decrypt(
                self.key, self.path.read_bytes(), profile=self.config.name, label="ledger"
            )
            try:
                connection.deserialize(plaintext)
                connection.execute("PRAGMA schema_version").fetchone()
            except sqlite3.DatabaseError as error:
                raise EncryptedStorageError("ledger SQLite image is invalid") from error
        return connection

    def _save(self, connection: sqlite3.Connection) -> None:
        atomic_write(
            self.path,
            encrypt(self.key, connection.serialize(), profile=self.config.name, label="ledger"),
        )

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = self._load()
        try:
            yield connection
            connection.commit()
            self._save(connection)
        finally:
            connection.close()


def export_backup(config: ProfileConfig, destination: Path) -> Path:
    source = profile_dir(config.name)
    destination = destination.expanduser().resolve()
    if not source.is_dir():
        raise EncryptedStorageError("profile directory not found")
    if destination.exists():
        raise EncryptedStorageError(f"backup destination already exists:{destination}")
    _private_directory(destination.parent)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    _private_tree(destination)
    return destination


def _private_tree(root: Path) -> None:
    root.chmod(0o700)
    for path in root.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
        elif path.is_dir():
            path.chmod(0o700)


def _backup_profile(source: Path) -> ProfileConfig:
    try:
        value = json.loads((source / "profile.json").read_text())
        return ProfileConfig(
            name=value["name"],
            key_file=value["key_file"],
            providers=tuple(value.get("providers", ("csv", "moomoo"))),
            benchmarks=tuple(value.get("benchmarks", ())),
            schema_version=int(value.get("schema_version", 1)),
            llm=LLMSettings(**value.get("llm", {})),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise EncryptedStorageError("backup profile configuration is invalid") from error


def restore_backup(source: Path) -> ProfileConfig:
    source = source.expanduser()
    if source.is_symlink() or not source.is_dir():
        raise EncryptedStorageError("backup source must be a regular directory")
    source = source.resolve()
    if any(path.is_symlink() for path in source.rglob("*")):
        raise EncryptedStorageError("backup source must not contain symbolic links")
    config = _backup_profile(source)
    destination = profile_dir(config.name)
    if destination.exists():
        raise EncryptedStorageError("profile directory already exists")
    _private_directory(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{config.name}.restore-", dir=destination.parent))
    try:
        shutil.copytree(source, staging, copy_function=shutil.copy2, dirs_exist_ok=True)
        _private_tree(staging)
        if destination.exists():
            raise EncryptedStorageError("profile directory already exists")
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return config


def rotate_key(config: ProfileConfig, new_key_file: Path) -> ProfileConfig:
    old_key = read_key_file(Path(config.key_file))
    new_key_file = new_key_file.expanduser().resolve()
    generate_key_file(new_key_file)
    new_key = read_key_file(new_key_file)
    root = profile_dir(config.name)
    encrypted_paths = [root / "ledger.sqlite.enc", *sorted((root / "sources").glob("*.enc"))]
    staged: list[tuple[Path, Path]] = []
    try:
        for path in encrypted_paths:
            if not path.exists():
                continue
            label = "ledger" if path.name == "ledger.sqlite.enc" else f"source:{path.stem}"
            plaintext = decrypt(old_key, path.read_bytes(), profile=config.name, label=label)
            staged_path = path.with_name(f".{path.name}.rotating")
            atomic_write(staged_path, encrypt(new_key, plaintext, profile=config.name, label=label))
            staged.append((staged_path, path))
        for staged_path, destination in staged:
            os.replace(staged_path, destination)
    except Exception:
        for staged_path, _ in staged:
            staged_path.unlink(missing_ok=True)
        new_key_file.unlink(missing_ok=True)
        raise
    updated = ProfileConfig(
        config.name,
        str(new_key_file),
        config.providers,
        config.benchmarks,
        config.schema_version,
        config.llm,
    )
    save_profile(updated)
    return updated
