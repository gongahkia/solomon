# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pytest

from solomon.store.encryption import EncryptedArtifactStore
from solomon.store.factory import UnsupportedStoreBackend, create_knowledge_store
from solomon.store.postgres import PostgresKnowledgeStore
from solomon.store.sqlite import SQLiteKnowledgeStore
from tests.postgres_fake import FakePostgresConnection


def test_encrypted_artifact_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    encrypted = tmp_path / "snapshot.enc"
    decrypted = tmp_path / "snapshot.decrypted.json"

    passphrase = "-".join(["unit", "test", "only"])
    store = EncryptedArtifactStore(passphrase=passphrase)
    manifest = store.encrypt_file(source, encrypted)
    store.decrypt_file(encrypted, decrypted, manifest=manifest)

    assert encrypted.read_bytes() != source.read_bytes()
    assert decrypted.read_text(encoding="utf-8") == '{"ok": true}'


def test_store_factory_switches_on_database_url(tmp_path: Path) -> None:
    sqlite = create_knowledge_store(f"sqlite:///{tmp_path / 'solomon.sqlite3'}")
    assert isinstance(sqlite, SQLiteKnowledgeStore)
    assert sqlite.path.name == "solomon.sqlite3"

    postgres = create_knowledge_store(
        "postgresql://localhost/solomon",
        postgres_connect=lambda _dsn: FakePostgresConnection(tmp_path / "pg.sqlite3"),
    )
    assert isinstance(postgres, PostgresKnowledgeStore)

    with pytest.raises(UnsupportedStoreBackend, match="unsupported store backend"):
        create_knowledge_store("mysql://localhost/solomon")
