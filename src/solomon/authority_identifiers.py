# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.contracts import AuthoritySource
from solomon.currency.models import new_uuid7, now_utc


class CanonicalAuthorityIdentifier(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    source_id: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    normalized_identifier: str = Field(min_length=1)
    canonical_id: str = Field(min_length=1)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())


class SQLiteAuthorityIdentifierStore:
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
                CREATE TABLE IF NOT EXISTS authority_identifiers (
                    identifier_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    normalized_identifier TEXT NOT NULL,
                    identifier_json TEXT NOT NULL,
                    UNIQUE(source_id, normalized_identifier)
                )
                """
            )

    def resolve(self, source: AuthoritySource, source_identifier: str) -> CanonicalAuthorityIdentifier:
        normalized = normalize_authority_identifier(source_identifier)
        row = self._conn.execute(
            """
            SELECT identifier_json FROM authority_identifiers
            WHERE source_id = ? AND normalized_identifier = ?
            """,
            (source.id, normalized),
        ).fetchone()
        if row is not None:
            return CanonicalAuthorityIdentifier.model_validate_json(str(row["identifier_json"]))
        canonical_id = f"authority:{source.id}:{hashlib.sha256(normalized.encode()).hexdigest()[:32]}"
        identifier = CanonicalAuthorityIdentifier(
            source_id=source.id,
            source_identifier=source_identifier,
            normalized_identifier=normalized,
            canonical_id=canonical_id,
        )
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO authority_identifiers
                (identifier_id, source_id, normalized_identifier, identifier_json)
                VALUES (?, ?, ?, ?)
                """,
                (identifier.id, identifier.source_id, identifier.normalized_identifier, identifier.model_dump_json()),
            )
        return identifier


def normalize_authority_identifier(identifier: str) -> str:
    value = identifier.strip()
    if not value:
        raise ValueError("authority identifier is required")
    if "://" not in value:
        return value
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("authority URL identifier must include scheme and host")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    if not host:
        raise ValueError("authority URL identifier must include a host")
    port = parsed.port
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = host if default_port or port is None else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


__all__ = ["CanonicalAuthorityIdentifier", "SQLiteAuthorityIdentifierStore", "normalize_authority_identifier"]
