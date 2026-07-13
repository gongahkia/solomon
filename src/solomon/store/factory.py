# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from solomon.graph.store import GraphStore
from solomon.graph.types import DependencyGraphProtocol
from solomon.orchestrator.retrieval import RetrievalEmbeddingProvider, RetrievalIndexProtocol, SQLiteRetrievalIndex
from solomon.store.postgres import ConnectCallable, PostgresGraphStore, PostgresKnowledgeStore, PostgresRetrievalIndex
from solomon.store.sqlite import SQLiteKnowledgeStore
from solomon.store.types import KnowledgeStoreProtocol


class UnsupportedStoreBackend(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageBundle:
    store: KnowledgeStoreProtocol
    graph: DependencyGraphProtocol
    index: RetrievalIndexProtocol


def create_knowledge_store(
    database_url: str,
    *,
    postgres_connect: ConnectCallable | None = None,
    postgres_schema: str | None = None,
) -> KnowledgeStoreProtocol:
    if _is_postgres_url(database_url):
        return PostgresKnowledgeStore(database_url, connect=postgres_connect, schema=postgres_schema)
    return SQLiteKnowledgeStore(_sqlite_path_from_url(database_url))


def create_storage_bundle(
    database_url: str,
    *,
    postgres_connect: ConnectCallable | None = None,
    postgres_schema: str | None = None,
    embedding_provider: RetrievalEmbeddingProvider | None = None,
) -> StorageBundle:
    parsed = urlparse(database_url)
    if parsed.scheme in {"", "sqlite"}:
        path = _sqlite_path_from_url(database_url)
        return StorageBundle(
            store=SQLiteKnowledgeStore(path),
            graph=GraphStore(path),
            index=SQLiteRetrievalIndex(path, provider=embedding_provider),
        )
    if _is_postgres_url(database_url):
        return StorageBundle(
            store=PostgresKnowledgeStore(database_url, connect=postgres_connect, schema=postgres_schema),
            graph=PostgresGraphStore(database_url, connect=postgres_connect, schema=postgres_schema),
            index=PostgresRetrievalIndex(
                database_url,
                connect=postgres_connect,
                schema=postgres_schema,
                provider=embedding_provider,
            ),
        )
    raise UnsupportedStoreBackend(f"unsupported store backend: {parsed.scheme}")


def _is_postgres_url(database_url: str) -> bool:
    return urlparse(database_url).scheme in {"postgres", "postgresql"}


def _sqlite_path_from_url(database_url: str) -> Path:
    parsed = urlparse(database_url)
    if parsed.scheme == "":
        return Path(database_url)
    if parsed.scheme != "sqlite":
        raise UnsupportedStoreBackend(f"unsupported store backend: {parsed.scheme}")
    raw_path = parsed.path
    if raw_path.startswith("/./"):
        raw_path = raw_path[1:]
    return Path(raw_path if raw_path else "./solomon-data/solomon.sqlite3")
