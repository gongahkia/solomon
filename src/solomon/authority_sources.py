# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3
from pathlib import Path

from solomon.contracts import AuthoritySource


class AuthoritySourceNotFoundError(KeyError):
    pass


class SQLiteAuthoritySourceRegistry:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.initialize()

    def close(self) -> None:
        self._conn.close()

    def initialize(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authority_sources (
                    source_id TEXT PRIMARY KEY,
                    canonical_namespace TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    source_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_authority_sources_namespace "
                "ON authority_sources(canonical_namespace, enabled)"
            )

    def register(self, source: AuthoritySource) -> AuthoritySource:
        existing = self._conn.execute(
            "SELECT source_json FROM authority_sources WHERE source_id = ?",
            (source.id,),
        ).fetchone()
        if existing is not None:
            persisted = AuthoritySource.model_validate_json(str(existing["source_json"]))
            if persisted == source:
                return persisted
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO authority_sources (source_id, canonical_namespace, enabled, source_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    canonical_namespace = excluded.canonical_namespace,
                    enabled = excluded.enabled,
                    source_json = excluded.source_json
                """,
                (source.id, source.canonical_namespace, int(source.enabled), source.model_dump_json()),
            )
        return source

    def get(self, source_id: str) -> AuthoritySource:
        row = self._conn.execute(
            "SELECT source_json FROM authority_sources WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if row is None:
            raise AuthoritySourceNotFoundError(source_id)
        return AuthoritySource.model_validate_json(str(row["source_json"]))

    def list(self, *, enabled: bool | None = None) -> list[AuthoritySource]:
        if enabled is None:
            rows = self._conn.execute("SELECT source_json FROM authority_sources ORDER BY source_id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT source_json FROM authority_sources WHERE enabled = ? ORDER BY source_id",
                (int(enabled),),
            ).fetchall()
        return [AuthoritySource.model_validate_json(str(row["source_json"])) for row in rows]


__all__ = ["AuthoritySourceNotFoundError", "SQLiteAuthoritySourceRegistry"]
