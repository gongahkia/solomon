from __future__ import annotations

import json
from pathlib import Path

import pytest

from stonks_cli.config import (
    DividendSettings,
    ProfileConfig,
    config_path,
    disable_provider,
    enable_provider,
    load_profile,
    profile_dir,
    save_profile,
)
from stonks_cli.errors import EncryptedStorageError, KeyFileError, ProfileError
from stonks_cli.storage import (
    EncryptedLedger,
    EncryptedStorageMigration,
    EncryptedStorageMigrationRegistry,
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


def test_storage_diagnostics_redact_key_paths_and_profile_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    key_path = tmp_path / "private-key"
    with pytest.raises(KeyFileError) as key_error:
        read_key_file(key_path)
    assert str(key_path) not in str(key_error.value)
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    with pytest.raises(ProfileError) as profile_error:
        load_profile("confidential")
    assert "confidential" not in str(profile_error.value)


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


def test_profile_dividend_credit_settings_are_explicit_and_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    config = ProfileConfig(
        "personal",
        str(tmp_path / "personal.key"),
        dividends=DividendSettings(True, True),
    )

    save_profile(config)

    assert load_profile("personal") == config
    assert json.loads(config_path("personal").read_text())["dividends"] == {
        "allow_currency_conversion": True,
        "allow_explicit_credit": True,
    }
    with pytest.raises(ProfileError, match="requires explicit credit"):
        DividendSettings(False, True)


def test_profile_config_canonicalizes_configured_provider_identifiers(tmp_path: Path) -> None:
    config = ProfileConfig(
        "personal", str(tmp_path / "personal.key"), providers=(" CSV ", " Moomoo ")
    )

    assert config.providers == ("csv", "moomoo")


def test_profile_provider_lifecycle_updates_a_validated_configuration(tmp_path: Path) -> None:
    config = ProfileConfig("personal", str(tmp_path / "personal.key"), providers=("csv",))

    enabled = enable_provider(config, " moomoo ")

    assert enabled.providers == ("csv", "moomoo")
    assert disable_provider(enabled, "csv").providers == ("moomoo",)
    with pytest.raises(ProfileError, match="not enabled"):
        disable_provider(enabled, "fixture")
    with pytest.raises(ProfileError, match="at least one"):
        disable_provider(config, "csv")


@pytest.mark.parametrize(
    ("providers", "error"),
    (
        ((), "at least one"),
        (("csv", "CSV"), "duplicates"),
        (("unknown",), "unavailable"),
        ((" ",), "identifier"),
    ),
)
def test_profile_config_rejects_invalid_provider_configuration(
    tmp_path: Path, providers: tuple[str, ...], error: str
) -> None:
    with pytest.raises(ProfileError, match=error):
        ProfileConfig("personal", str(tmp_path / "personal.key"), providers=providers)


def test_aes_gcm_envelope_has_versioned_header_and_rejects_truncation() -> None:
    key = b"x" * 32
    payload = encrypt(key, b"secret", profile="personal", label="ledger")
    assert payload.startswith(b"STONKS\x01\x00")
    assert b"secret" not in payload
    assert decrypt(key, payload, profile="personal", label="ledger") == b"secret"
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(key, payload[:-1], profile="personal", label="ledger")


def test_encrypted_storage_migration_registry_requires_contiguous_versions() -> None:
    def upgrade(payload: bytes, _: bytes, __: str, ___: str) -> bytes:
        return b"STONKS\x02\x00" + payload[8:]

    registry = EncryptedStorageMigrationRegistry(
        (EncryptedStorageMigration(2, "upgrade", upgrade),)
    )
    migrated = registry.migrate(b"STONKS\x01\x00payload", b"x" * 32, "personal", "ledger")
    assert registry.latest_version == 2
    assert migrated == b"STONKS\x02\x00payload"
    with pytest.raises(ValueError, match="contiguous"):
        EncryptedStorageMigrationRegistry((EncryptedStorageMigration(3, "upgrade", upgrade),))
    with pytest.raises(ValueError, match="name"):
        EncryptedStorageMigration(2, "", upgrade)


def test_decrypt_rejects_unregistered_envelope_version() -> None:
    with pytest.raises(EncryptedStorageError, match="unsupported"):
        decrypt(b"x" * 32, b"STONKS\x02\x00" + b"x" * 28, profile="personal", label="ledger")


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
