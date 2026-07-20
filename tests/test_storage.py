from __future__ import annotations

import json
from pathlib import Path

import pytest

from stonks_cli.config import ProfileConfig, config_path, load_profile, profile_dir, save_profile
from stonks_cli.errors import EncryptedStorageError, KeyFileError
from stonks_cli.storage import (
    EncryptedLedger,
    atomic_write,
    decrypt,
    encrypt,
    export_backup,
    generate_key_file,
    read_key_file,
    restore_backup,
    rotate_key,
)


def test_key_file_is_private_and_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "profile.key"
    generate_key_file(path)
    assert len(read_key_file(path)) == 32
    assert path.stat().st_mode & 0o077 == 0


def test_key_file_rejects_group_readable_file(tmp_path: Path) -> None:
    path = tmp_path / "profile.key"
    generate_key_file(path)
    path.chmod(0o640)
    with pytest.raises(KeyFileError, match="private"):
        read_key_file(path)


def test_key_file_rejects_non_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "profile.key"
    generate_key_file(path)
    monkeypatch.setattr("stonks_cli.storage.os.getuid", lambda: path.stat().st_uid + 1)
    with pytest.raises(KeyFileError, match="owner"):
        read_key_file(path)


def test_key_file_rejects_non_256_bit_content(tmp_path: Path) -> None:
    path = tmp_path / "profile.key"
    path.write_bytes(b"x" * 31)
    path.chmod(0o600)
    with pytest.raises(KeyFileError, match="32 raw bytes"):
        read_key_file(path)


def test_atomic_write_preserves_existing_file_when_replacement_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def replace_error(_: str, __: str) -> None:
        raise OSError

    path = tmp_path / "nested" / "ledger.sqlite.enc"
    atomic_write(path, b"old")
    monkeypatch.setattr("stonks_cli.storage.os.replace", replace_error)
    with pytest.raises(OSError):
        atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert path.stat().st_mode & 0o077 == 0
    assert path.parent.stat().st_mode & 0o077 == 0
    assert not list(path.parent.glob(".ledger.sqlite.enc.*"))


def test_profile_directory_layout_uses_expected_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    config = ProfileConfig("personal", str(key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    digest = ledger.archive_source(b"source")
    root = profile_dir("personal")
    assert root == tmp_path / "home" / "profiles" / "personal"
    assert config_path("personal") == root / "profile.json"
    assert config_path("personal").is_file()
    assert ledger.path == root / "ledger.sqlite.enc"
    assert ledger.sources == root / "sources"
    assert (ledger.sources / f"{digest}.enc").is_file()
    assert root.stat().st_mode & 0o077 == 0


def test_profile_config_schema_round_trips_versioned_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    config = ProfileConfig(
        "personal",
        str(tmp_path / "personal.key"),
        providers=("csv",),
        benchmarks=("SPY",),
        schema_version=1,
    )
    save_profile(config)
    assert load_profile("personal") == config
    assert json.loads(config_path("personal").read_text()) == {
        "benchmarks": ["SPY"],
        "key_file": str(tmp_path / "personal.key"),
        "name": "personal",
        "providers": ["csv"],
        "schema_version": 1,
    }


def test_aes_gcm_envelope_has_versioned_header_and_rejects_truncation() -> None:
    key = b"x" * 32
    payload = encrypt(key, b"secret", profile="personal", label="ledger")
    assert payload.startswith(b"STONKS\x01\x00")
    assert b"secret" not in payload
    assert decrypt(key, payload, profile="personal", label="ledger") == b"secret"
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(key, payload[:-1], profile="personal", label="ledger")


def test_envelope_rejects_wrong_aad() -> None:
    key = b"x" * 32
    payload = encrypt(key, b"secret", profile="personal", label="ledger")
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(key, payload, profile="other", label="ledger")
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(key, payload, profile="personal", label="source:other")


def test_archived_source_is_encrypted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    config = ProfileConfig("personal", str(key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    source = b"account_id,occurred_at\n"
    digest = ledger.archive_source(source)
    path = ledger.sources / f"{digest}.enc"
    stored = path.read_bytes()
    assert b"account_id" not in stored
    assert decrypt(ledger.key, stored, profile="personal", label=f"source:{digest}") == source
    assert ledger.archive_source(source) == digest
    assert path.read_bytes() == stored


def test_ledger_rejects_tampered_encrypted_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    with ledger.connection() as connection:
        connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY)")
    payload = bytearray(ledger.path.read_bytes())
    payload[-1] ^= 1
    ledger.path.write_bytes(payload)
    with pytest.raises(EncryptedStorageError, match="authentication"):
        with ledger.connection():
            pass


def test_ledger_rejects_authenticated_non_sqlite_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    with ledger.connection():
        pass
    ledger.path.write_bytes(
        encrypt(ledger.key, b"not a SQLite image", profile="personal", label="ledger")
    )
    with pytest.raises(EncryptedStorageError, match="SQLite image"):
        with ledger.connection():
            pass


def test_ledger_serializes_in_memory_sqlite_as_encrypted_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    with ledger.connection() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('serialized-secret')")
    encrypted = ledger.path.read_bytes()
    assert encrypted.startswith(b"STONKS\x01\x00")
    assert b"serialized-secret" not in encrypted


def test_ledger_restores_serialized_in_memory_sqlite_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    ledger = EncryptedLedger(ProfileConfig("personal", str(key)))
    with ledger.connection() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('restored')")
    with ledger.connection() as connection:
        assert connection.execute("SELECT value FROM records").fetchone()["value"] == "restored"


def test_backup_and_key_rotation_preserve_encrypted_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    old_key = tmp_path / "old.key"
    generate_key_file(old_key)
    config = ProfileConfig("personal", str(old_key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    digest = ledger.archive_source(b"source")
    old_key_data = read_key_file(old_key)
    with ledger.connection() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('rotated')")
    backup = export_backup(config, tmp_path / "backup")
    assert (backup / "profile.json").is_file()
    assert (backup / "sources" / f"{digest}.enc").is_file()
    assert backup.stat().st_mode & 0o077 == 0
    assert (backup / "sources" / f"{digest}.enc").stat().st_mode & 0o077 == 0
    with pytest.raises(EncryptedStorageError, match="already exists"):
        export_backup(config, backup)
    updated = rotate_key(config, tmp_path / "new.key")
    assert load_profile("personal") == updated
    assert (
        decrypt(
            read_key_file(Path(updated.key_file)),
            (ledger.sources / f"{digest}.enc").read_bytes(),
            profile="personal",
            label=f"source:{digest}",
        )
        == b"source"
    )
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(
            old_key_data,
            (ledger.sources / f"{digest}.enc").read_bytes(),
            profile="personal",
            label=f"source:{digest}",
        )
    with EncryptedLedger(updated).connection() as connection:
        assert connection.execute("SELECT value FROM records").fetchone()["value"] == "rotated"


def test_backup_restore_preserves_encrypted_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_home = tmp_path / "source-home"
    monkeypatch.setenv("STONKS_CLI_HOME", str(source_home))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    config = ProfileConfig("personal", str(key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    digest = ledger.archive_source(b"source")
    with ledger.connection() as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('backup')")
    backup = export_backup(config, tmp_path / "backup")
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "restore-home"))
    restored = restore_backup(backup)
    assert restored == config
    assert load_profile("personal") == config
    restored_ledger = EncryptedLedger(restored)
    restored_source = restored_ledger.sources / f"{digest}.enc"
    assert (
        decrypt(
            read_key_file(key),
            restored_source.read_bytes(),
            profile="personal",
            label=f"source:{digest}",
        )
        == b"source"
    )
    with restored_ledger.connection() as connection:
        assert connection.execute("SELECT value FROM records").fetchone()["value"] == "backup"
    with pytest.raises(EncryptedStorageError, match="already exists"):
        restore_backup(backup)
