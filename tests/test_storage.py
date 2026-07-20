from __future__ import annotations

from pathlib import Path

import pytest

from stonks_cli.config import ProfileConfig, config_path, load_profile, profile_dir, save_profile
from stonks_cli.errors import EncryptedStorageError, KeyFileError
from stonks_cli.storage import (
    EncryptedLedger,
    decrypt,
    encrypt,
    export_backup,
    generate_key_file,
    read_key_file,
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


def test_envelope_rejects_wrong_aad() -> None:
    key = b"x" * 32
    payload = encrypt(key, b"secret", profile="personal", label="ledger")
    with pytest.raises(EncryptedStorageError, match="authentication"):
        decrypt(key, payload, profile="other", label="ledger")


def test_archived_source_is_encrypted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / "personal.key"
    generate_key_file(key)
    config = ProfileConfig("personal", str(key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    digest = ledger.archive_source(b"account_id,occurred_at\n")
    stored = (ledger.sources / f"{digest}.enc").read_bytes()
    assert b"account_id" not in stored


def test_backup_and_key_rotation_preserve_encrypted_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    old_key = tmp_path / "old.key"
    generate_key_file(old_key)
    config = ProfileConfig("personal", str(old_key))
    save_profile(config)
    ledger = EncryptedLedger(config)
    digest = ledger.archive_source(b"source")
    backup = export_backup(config, tmp_path / "backup")
    assert (backup / "sources" / f"{digest}.enc").is_file()
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
