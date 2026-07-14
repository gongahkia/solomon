from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from stonks_cli.paths import default_state_dir
from stonks_cli.vnext.filesystem import ensure_private_directory

RUNTIME_ROOT_ENV = "STONKS_CLI_VNEXT_RUNTIME_DIR"


class RuntimeDirectory(StrEnum):
    RUNS = "runs"
    SNAPSHOTS = "snapshots"
    REPORTS = "reports"
    QUEUE = "queue"
    BACKUPS = "backups"


@dataclass(frozen=True)
class RuntimeDirectories:
    root: Path

    def path_for(self, directory: RuntimeDirectory | str) -> Path:
        try:
            name = RuntimeDirectory(directory)
        except (TypeError, ValueError) as error:
            raise ValueError(f"unknown runtime directory:{directory}") from error
        return self.root / name.value

    def ensure(self) -> None:
        ensure_private_directory(self.root)
        for directory in RuntimeDirectory:
            path = self.path_for(directory)
            ensure_private_directory(path)


def runtime_directories(root: Path | None = None) -> RuntimeDirectories:
    if root is None:
        override = os.getenv(RUNTIME_ROOT_ENV)
        root = Path(override).expanduser() if override is not None else default_state_dir() / "vnext"
    if not root.is_absolute():
        raise ValueError("runtime root must be absolute")
    return RuntimeDirectories(root.resolve())
