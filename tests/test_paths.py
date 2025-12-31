from __future__ import annotations

from pathlib import Path

from stonks_cli.config import config_path


def test_config_path_expands_user(monkeypatch, tmp_path):
    # Ensure ~ expansion is stable across platforms by pinning HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STONKS_CLI_CONFIG", "~/stonks-config.json")

    p = config_path()
    assert p == tmp_path / "stonks-config.json"
    assert isinstance(p, Path)
