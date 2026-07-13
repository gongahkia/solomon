# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any


class FakePostgresConnection:
    """SQLite-backed adapter for exercising Postgres SQL paths without a server."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        if "CREATE EXTENSION IF NOT EXISTS vector" in sql:
            return self._conn.execute("SELECT 1")
        if "FROM pg_extension WHERE extname" in sql:
            return self._conn.execute("SELECT 1")
        return self._conn.execute(_translate(sql), params)

    def begin(self) -> None:
        self._conn.execute("BEGIN")

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def _translate(sql: str) -> str:
    translated = sql.replace("%s", "?")
    translated = re.sub(r'CREATE SCHEMA IF NOT EXISTS "[A-Za-z_][A-Za-z0-9_]*"', "SELECT 1", translated)
    translated = re.sub(
        r'"([A-Za-z_][A-Za-z0-9_]*)"\."([A-Za-z_][A-Za-z0-9_]*)"',
        r'"\1__\2"',
        translated,
    )
    translated = translated.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    translated = translated.replace(" ADD COLUMN IF NOT EXISTS ", " ADD COLUMN ")
    translated = re.sub(r"::vector(?:\([0-9]+\))?", "", translated)
    translated = re.sub(
        r"(CREATE INDEX IF NOT EXISTS .+? ON .+?) USING hnsw \(embedding vector_cosine_ops\)",
        r"\1(embedding)",
        translated,
        flags=re.DOTALL,
    )
    translated = re.sub(r"\bEXCLUDED\.", "excluded.", translated)
    translated = re.sub(r"\bTRUNCATE TABLE\s+([A-Za-z0-9_\".]+)", r"DELETE FROM \1", translated)
    return translated
