# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from typing import Any

from solomon.store.sqlite import StoreError

ConnectCallable = Callable[[str], Any]
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PostgresDependencyError(StoreError):
    """Raised when the optional Postgres driver is unavailable."""


class PostgresVectorExtensionError(StoreError):
    """Raised when the required pgvector extension is unavailable."""


def default_connect(dsn: str) -> Any:
    try:
        psycopg = importlib.import_module("psycopg")
        rows = importlib.import_module("psycopg.rows")
    except ModuleNotFoundError as exc:
        raise PostgresDependencyError(
            "Postgres backend requires the optional server dependency: install solomon[server]"
        ) from exc
    return psycopg.connect(dsn, row_factory=rows.dict_row, autocommit=False)


def normalize_schema(schema: str | None) -> str | None:
    if schema is None:
        return None
    normalized = re.sub(r"[^A-Za-z0-9_]", "_", schema)
    if not normalized or normalized[0].isdigit():
        normalized = f"tenant_{normalized}"
    if not IDENTIFIER_RE.fullmatch(normalized):
        raise StoreError(f"invalid Postgres schema identifier: {schema}")
    return normalized


def quote_identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise StoreError(f"invalid SQL identifier: {value}")
    return f'"{value}"'


def qualified(schema: str | None, table: str) -> str:
    quoted_table = quote_identifier(table)
    if schema is None:
        return quoted_table
    return f"{quote_identifier(schema)}.{quoted_table}"
