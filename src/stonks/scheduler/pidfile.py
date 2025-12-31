from __future__ import annotations

import atexit
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PidFile:
    path: Path

    def remove(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except Exception:
            pass


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # If we don't have permission to signal it, assume it's running.
        return True
    except Exception:
        return False
    return True


def acquire_pid_file(path: Path) -> PidFile:
    """Acquire a pid file lock.

    - Creates the pid file exclusively.
    - If it already exists and the pid is running, raise.
    - If it exists but is stale, overwrite.

    Best-effort cross-platform behavior; strongest on POSIX.
    """

    path.parent.mkdir(parents=True, exist_ok=True)

    pid = os.getpid()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(str(path), flags, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(str(pid))
    except FileExistsError:
        try:
            existing = path.read_text(encoding="utf-8").strip()
            existing_pid = int(existing)
        except Exception:
            existing_pid = -1

        if _pid_is_running(existing_pid):
            raise RuntimeError(f"Scheduler already running (pid={existing_pid})")

        # Stale pid; overwrite.
        path.write_text(str(pid), encoding="utf-8")

    pidfile = PidFile(path=path)
    atexit.register(pidfile.remove)
    return pidfile
