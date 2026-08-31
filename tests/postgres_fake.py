# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import math
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
        self._conn.create_function("vector_cosine_distance", 2, _vector_cosine_distance)
        self._conn.create_function("tsv_matches", 2, _tsv_matches)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        if "CREATE EXTENSION IF NOT EXISTS vector" in sql:
            return self._conn.execute("SELECT 1")
        if "FROM pg_extension WHERE extname" in sql:
            return self._conn.execute("SELECT 1")
        add_column = re.fullmatch(
            r'\s*ALTER TABLE\s+((?:"[A-Za-z_][A-Za-z0-9_]*"\.)?"[A-Za-z_][A-Za-z0-9_]*")\s+'
            r"ADD COLUMN IF NOT EXISTS\s+([A-Za-z_][A-Za-z0-9_]*)\s+.+",
            sql,
            flags=re.DOTALL,
        )
        if add_column is not None:
            table = _translate(add_column.group(1))
            column = add_column.group(2)
            columns = {str(row["name"]) for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column in columns:
                return self._conn.execute("SELECT 1")
            return self._conn.execute(_translate(sql), params)
        if re.fullmatch(
            r'\s*ALTER TABLE\s+(?:"[A-Za-z_][A-Za-z0-9_]*"\.)?"[A-Za-z_][A-Za-z0-9_]*"\s+'
            r"DROP CONSTRAINT IF EXISTS\s+[A-Za-z_][A-Za-z0-9_]*\s*",
            sql,
        ):
            return self._conn.execute("SELECT 1")
        match = re.fullmatch(
            r'\s*ALTER TABLE\s+((?:"[A-Za-z_][A-Za-z0-9_]*"\.)?"[A-Za-z_][A-Za-z0-9_]*")\s+'
            r"ALTER COLUMN\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET NOT NULL\s*",
            sql,
        )
        if match is not None:
            table = _translate(match.group(1))
            column = match.group(2)
            null_count = self._conn.execute(
                f'SELECT COUNT(*) FROM {table} WHERE "{column}" IS NULL'  # noqa: S608 - constrained DDL regex.
            ).fetchone()[0]
            if null_count:
                raise sqlite3.IntegrityError(f"column {column} contains null values")
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
    translated = translated.replace("::tsvector", "")
    translated = re.sub(r"to_tsvector\('simple', ([A-Za-z_][A-Za-z0-9_]*)\)", r"\1", translated)
    translated = re.sub(r"to_tsvector\('simple', \?\)", "?", translated)
    translated = re.sub(
        r"ts_rank_cd\([^,]+, plainto_tsquery\('simple', \?\)\)",
        "(? * 0 + 1.0)",
        translated,
    )
    translated = re.sub(
        r"([A-Za-z_]+\.content_tsv) @@ plainto_tsquery\('simple', \?\)",
        r"tsv_matches(\1, ?)",
        translated,
    )
    translated = re.sub(
        r"([A-Za-z_]+\.embedding) <=> \?",
        r"vector_cosine_distance(\1, ?)",
        translated,
    )
    translated = re.sub(
        r"(CREATE INDEX IF NOT EXISTS .+? ON .+?) USING hnsw \(embedding vector_cosine_ops\)",
        r"\1(embedding)",
        translated,
        flags=re.DOTALL,
    )
    translated = re.sub(
        r"(CREATE INDEX IF NOT EXISTS .+? ON .+?) USING gin \(content_tsv\)",
        r"\1(content_tsv)",
        translated,
        flags=re.DOTALL,
    )
    translated = re.sub(r"\bEXCLUDED\.", "excluded.", translated)
    translated = re.sub(r"\bTRUNCATE TABLE\s+([A-Za-z0-9_\".]+)", r"DELETE FROM \1", translated)
    return translated


def _vector_cosine_distance(left: str, right: str) -> float:
    left_vector = json.loads(left)
    right_vector = json.loads(right)
    magnitude = math.sqrt(sum(value * value for value in left_vector) * sum(value * value for value in right_vector))
    if magnitude == 0:
        return 1.0
    return 1.0 - sum(a * b for a, b in zip(left_vector, right_vector, strict=True)) / magnitude


def _tsv_matches(content: str, query: str) -> bool:
    content_terms = set(re.findall(r"[A-Za-z0-9_§.-]+", content.lower()))
    query_terms = set(re.findall(r"[A-Za-z0-9_§.-]+", query.lower()))
    return query_terms.issubset(content_terms)
