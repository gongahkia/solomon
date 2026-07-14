from __future__ import annotations

from pathlib import Path

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


def ensure_private_directory(path: Path) -> None:
    _reject_symlink(path)
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    if not path.is_dir():
        raise NotADirectoryError(path)
    path.chmod(PRIVATE_DIRECTORY_MODE)
    _assert_owner_only(path)


def enforce_private_file(path: Path) -> None:
    _reject_symlink(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    path.chmod(PRIVATE_FILE_MODE)
    _assert_owner_only(path)


def _reject_symlink(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"runtime path must not be a symlink:{path}")


def _assert_owner_only(path: Path) -> None:
    if path.stat().st_mode & 0o077:
        raise PermissionError(f"runtime path permissions are not owner-only:{path}")
