# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from solomon.store.sqlite import SQLiteKnowledgeStore


class UnsupportedStoreBackend(RuntimeError):
    pass


def create_knowledge_store(database_url: str) -> SQLiteKnowledgeStore:
    parsed = urlparse(database_url)
    if parsed.scheme in {"", "sqlite"}:
        if parsed.scheme == "sqlite":
            raw_path = parsed.path
            path = raw_path if raw_path else "./solomon-data/solomon.sqlite3"
        else:
            path = database_url
        return SQLiteKnowledgeStore(Path(path))
    if parsed.scheme in {"postgres", "postgresql"}:
        raise UnsupportedStoreBackend(
            "Postgres backend is a supported configuration switch but not installed in local SKU"
        )
    raise UnsupportedStoreBackend(f"unsupported store backend: {parsed.scheme}")
