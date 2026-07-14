from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from stonks_cli.paths import default_state_dir

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
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise NotADirectoryError(f"runtime root is not a directory:{self.root}")
        for directory in RuntimeDirectory:
            path = self.path_for(directory)
            path.mkdir(exist_ok=True)
            if not path.is_dir():
                raise NotADirectoryError(f"runtime path is not a directory:{path}")


def runtime_directories(root: Path | None = None) -> RuntimeDirectories:
    if root is None:
        override = os.getenv(RUNTIME_ROOT_ENV)
        root = Path(override).expanduser() if override is not None else default_state_dir() / "vnext"
    if not root.is_absolute():
        raise ValueError("runtime root must be absolute")
    return RuntimeDirectories(root.resolve())
