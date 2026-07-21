from __future__ import annotations

from pathlib import Path

import pytest

from stonks_cli.config import ProfileConfig
from stonks_cli.storage import EncryptedLedger, generate_key_file


def encrypted_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str = "personal"
) -> EncryptedLedger:
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    key = tmp_path / f"{profile}.key"
    generate_key_file(key)
    return EncryptedLedger(ProfileConfig(profile, str(key)))
