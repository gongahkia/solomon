from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

from stonks_cli.vnext.foundation import as_utc


@dataclass(frozen=True)
class DataRetentionPolicy:
    max_age: timedelta
    protected_relative_paths: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.max_age, timedelta) or self.max_age <= timedelta():
            raise ValueError("data-retention maximum age is invalid")
        if not isinstance(self.protected_relative_paths, frozenset) or not all(_is_relative_path(path) for path in self.protected_relative_paths):
            raise ValueError("data-retention protected paths are invalid")


@dataclass(frozen=True)
class DataRetentionReport:
    deleted_relative_paths: tuple[str, ...]
    retained_relative_paths: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(isinstance(paths, tuple) for paths in (self.deleted_relative_paths, self.retained_relative_paths)):
            raise TypeError("data-retention report paths are invalid")
        all_paths = (*self.deleted_relative_paths, *self.retained_relative_paths)
        if not all(_is_relative_path(path) for path in all_paths) or len(set(all_paths)) != len(all_paths):
            raise ValueError("data-retention report paths are invalid")
        if self.deleted_relative_paths != tuple(sorted(self.deleted_relative_paths)) or self.retained_relative_paths != tuple(sorted(self.retained_relative_paths)):
            raise ValueError("data-retention report paths are not canonical")


def enforce_data_retention(root: Path, policy: DataRetentionPolicy, now: datetime) -> DataRetentionReport:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("data-retention root must be an absolute regular directory")
    if not isinstance(policy, DataRetentionPolicy):
        raise TypeError("data-retention policy is required")
    cutoff_timestamp = as_utc(now).timestamp() - policy.max_age.total_seconds()
    files = tuple(sorted((path for path in root.rglob("*") if path.is_file() or path.is_symlink()), key=lambda path: path.as_posix()))
    if any(path.is_symlink() for path in files):
        raise ValueError("data-retention root must not contain symlinks")
    deleted: list[str] = []
    retained: list[str] = []
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        if relative_path in policy.protected_relative_paths or path.stat().st_mtime >= cutoff_timestamp:
            retained.append(relative_path)
            continue
        path.unlink()
        deleted.append(relative_path)
    return DataRetentionReport(tuple(deleted), tuple(retained))


def _is_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in {"", ".", ".."} for part in path.parts)
