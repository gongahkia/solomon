from __future__ import annotations

import json
import stat
from dataclasses import dataclass
from pathlib import Path

LIVE_CONFIGURATION_VERSION = 1


@dataclass(frozen=True)
class DeferredLiveConfiguration:
    path: Path
    execution_mode: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("live configuration path must be absolute")
        if self.execution_mode != "disabled":
            raise ValueError("live configuration execution mode must be disabled")


def load_deferred_live_configuration(live_path: Path, primary_path: Path) -> DeferredLiveConfiguration:
    _validate_paths(live_path, primary_path)
    try:
        data = json.loads(live_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("live configuration cannot be loaded") from error
    if not isinstance(data, dict) or set(data) != {"version", "execution_mode"}:
        raise ValueError("live configuration fields are invalid")
    if type(data["version"]) is not int or data["version"] != LIVE_CONFIGURATION_VERSION:
        raise ValueError("live configuration version is invalid")
    if not isinstance(data["execution_mode"], str):
        raise ValueError("live configuration execution mode is invalid")
    return DeferredLiveConfiguration(live_path.resolve(), data["execution_mode"])


def _validate_paths(live_path: Path, primary_path: Path) -> None:
    if not isinstance(live_path, Path) or not isinstance(primary_path, Path):
        raise TypeError("configuration paths must be Path values")
    if not live_path.is_absolute() or not primary_path.is_absolute():
        raise ValueError("configuration paths must be absolute")
    if live_path.is_symlink():
        raise ValueError("live configuration path must not be a symlink")
    if live_path.resolve() == primary_path.resolve():
        raise ValueError("live configuration path must differ from primary configuration")
    try:
        metadata = live_path.stat()
    except OSError as error:
        raise FileNotFoundError("live configuration file is required") from error
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("live configuration path must be a regular file")
    if metadata.st_mode & 0o077:
        raise PermissionError("live configuration file permissions must be owner-only")
