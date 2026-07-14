from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SQLiteConnectionFactory:
    path: Path
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("SQLite path must be a Path")
        if not self.path.is_absolute():
            raise ValueError("SQLite path must be absolute")
        if not isinstance(self.timeout_seconds, (int, float)) or isinstance(self.timeout_seconds, bool):
            raise ValueError("SQLite timeout must be a positive finite number")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("SQLite timeout must be a positive finite number")

    def connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(self.path)
            connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", timeout=self.timeout_seconds, uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=self.timeout_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout_seconds * 1000)}")
        if read_only:
            connection.execute("PRAGMA query_only = ON")
        else:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
        return connection
