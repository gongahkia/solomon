from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_state_dir

APP_NAME = "stonks-cli"


def _override(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value).expanduser() if value else None


def _home_override() -> Path | None:
    return _override("STONKS_CLI_HOME")


def default_config_path() -> Path:
    if root := _home_override():
        return root / "config.json"
    return Path(user_config_dir(APP_NAME)) / "config.json"


def default_state_dir() -> Path:
    if path := _override("STONKS_CLI_STATE_DIR"):
        return path
    if root := _home_override():
        return root / "state"
    return Path(user_state_dir(APP_NAME))


def default_cache_dir() -> Path:
    if path := _override("STONKS_CLI_CACHE_DIR"):
        return path
    if root := _home_override():
        return root / "cache"
    return Path(user_cache_dir(APP_NAME))
