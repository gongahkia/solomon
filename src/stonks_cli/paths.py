from __future__ import annotations

from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_state_dir

APP_NAME = "stonks-cli"


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME)) / "config.json"


def default_state_dir() -> Path:
    return Path(user_state_dir(APP_NAME))


def default_cache_dir() -> Path:
    return Path(user_cache_dir(APP_NAME))
