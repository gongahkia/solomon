from __future__ import annotations

from pathlib import Path

from stonks_cli.config import config_path
from stonks_cli.paths import default_cache_dir, default_config_path, default_state_dir


def test_config_path_expands_user(monkeypatch, tmp_path):
    # Ensure ~ expansion is stable across platforms by pinning HOME.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("STONKS_CLI_CONFIG", "~/stonks-config.json")

    p = config_path()
    assert p == tmp_path / "stonks-config.json"
    assert isinstance(p, Path)


def test_home_override_isolates_all_managed_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path))

    assert default_config_path() == tmp_path / "config.json"
    assert default_state_dir() == tmp_path / "state"
    assert default_cache_dir() == tmp_path / "cache"


def test_specific_state_and_cache_overrides_win_over_home(monkeypatch, tmp_path):
    monkeypatch.setenv("STONKS_CLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("STONKS_CLI_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("STONKS_CLI_CACHE_DIR", str(tmp_path / "cache"))

    assert default_state_dir() == tmp_path / "state"
    assert default_cache_dir() == tmp_path / "cache"
