# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import SecretStr

from solomon.api.app import create_app
from solomon.api.auth import AuthPrincipal, scopes_for_roles
from solomon.api.service import DocumentSourceRequest, SolomonService, SourceDocumentIngestRequest
from solomon.config import Settings, content_envelope_from_settings, local_settings
from solomon.errors import PolicyRefusalError
from solomon.sources.models import CandidateClaim, DocumentSource, DocumentSourceKind, SourceDocument
from solomon.sources.store import SQLiteDocumentStore
from solomon.store.encryption import ContentEnvelopeCipher, ContentEnvelopeError

KEY = base64.b64encode(bytes(range(32))).decode("ascii")


def _cipher(*, key_ref: str = "kms://solomon/content/v1", key: str = KEY) -> ContentEnvelopeCipher:
    return ContentEnvelopeCipher(key_ref=key_ref, wrapping_key=SecretStr(key))


def test_document_and_candidate_content_are_enveloped_and_plaintext_rows_migrate(tmp_path: Path) -> None:
    path = tmp_path / "sources.sqlite3"
    plain = SQLiteDocumentStore(path)
    source = plain.upsert_source(
        DocumentSource(id="source-1", name="files", kind=DocumentSourceKind.FILESYSTEM, root_ref="/x")
    )
    document = plain.write_document(
        SourceDocument(
            id="document-1",
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="document-secret-729c",
        )
    )
    candidate = plain.add_candidate(
        CandidateClaim(
            id="candidate-1",
            document_id=document.id,
            content="candidate-secret-8a11",
            start_offset=0,
            end_offset=21,
        )
    )
    plain.close()

    encrypted = SQLiteDocumentStore(path, content_cipher=_cipher())

    assert encrypted.get_document(document.id).content == "document-secret-729c"
    assert encrypted.get_candidate(candidate.id).content == "candidate-secret-8a11"

    raw = sqlite3.connect(path)
    document_row = raw.execute(
        "SELECT document_json FROM source_documents WHERE document_id = ?", (document.id,)
    ).fetchone()
    candidate_row = raw.execute(
        "SELECT candidate_json FROM candidate_claims WHERE candidate_id = ?", (candidate.id,)
    ).fetchone()
    raw.close()
    assert document_row is not None
    assert candidate_row is not None
    document_json = document_row[0]
    candidate_json = candidate_row[0]
    assert "document-secret-729c" not in document_json
    assert "candidate-secret-8a11" not in candidate_json
    assert json.loads(document_json)["content"]["key_ref"] == "kms://solomon/content/v1"
    assert json.loads(candidate_json)["content"]["algorithm"] == "AES-256-GCM+AES-KW"


def test_content_envelope_rejects_tampering_and_unavailable_key_reference(tmp_path: Path) -> None:
    path = tmp_path / "sources.sqlite3"
    store = SQLiteDocumentStore(path, content_cipher=_cipher())
    source = store.upsert_source(
        DocumentSource(id="source-1", name="files", kind=DocumentSourceKind.FILESYSTEM, root_ref="/x")
    )
    document = store.write_document(
        SourceDocument(
            id="document-1",
            source_id=source.id,
            external_id="memo-1",
            filename="memo.txt",
            mime_type="text/plain",
            content="tamper-secret-2049",
        )
    )
    store.close()

    with pytest.raises(ContentEnvelopeError, match="key reference is unavailable"):
        SQLiteDocumentStore(path, content_cipher=_cipher(key_ref="kms://solomon/content/v2"))

    connection = sqlite3.connect(path)
    row = connection.execute(
        "SELECT document_json FROM source_documents WHERE document_id = ?", (document.id,)
    ).fetchone()
    assert row is not None
    payload = json.loads(row[0])
    ciphertext = payload["content"]["ciphertext_b64"]
    payload["content"]["ciphertext_b64"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    connection.execute(
        "UPDATE source_documents SET document_json = ? WHERE document_id = ?",
        (json.dumps(payload), document.id),
    )
    connection.commit()
    connection.close()

    with pytest.raises(ContentEnvelopeError, match="cannot be decrypted"):
        SQLiteDocumentStore(path, content_cipher=_cipher())


def test_content_encryption_settings_do_not_expose_key_material(tmp_path: Path) -> None:
    settings = local_settings(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        content_encryption_key_ref="kms://solomon/content/v1",
        content_encryption_key=SecretStr(KEY),
    )

    cipher = content_envelope_from_settings(settings)
    assert cipher is not None
    assert cipher.key_ref == "kms://solomon/content/v1"
    assert create_app(settings).state.service.document_store.content_cipher is not None
    diagnostics = settings.public_diagnostics()
    assert diagnostics["content_encryption_configured"] is True
    assert diagnostics["content_encryption_key_ref"] == "kms://solomon/content/v1"
    assert KEY not in json.dumps(diagnostics)

    with pytest.raises(ValueError, match="key reference and key"):
        Settings(content_encryption_key_ref="kms://solomon/content/v1")


def test_content_encryption_audits_actor_decision_and_correlation_and_denies_read_only_role(tmp_path: Path) -> None:
    service = SolomonService(
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        content_cipher=_cipher(),
    )
    curator = AuthPrincipal(
        subject="curator-1",
        role="curator",
        tenant_id="tenant-a",
        scopes=scopes_for_roles(frozenset({"curator"})),
        roles=frozenset({"curator"}),
    )
    integration = AuthPrincipal(
        subject="integration-1",
        role="integration",
        tenant_id="tenant-a",
        scopes=scopes_for_roles(frozenset({"integration"})),
        roles=frozenset({"integration"}),
    )

    with service.authorized_as(curator, "envelope-write"):
        source = service.register_document_source(
            DocumentSourceRequest(name="files", kind=DocumentSourceKind.FILESYSTEM, root_ref="/x")
        )
        document, candidates = service.ingest_source_document(
            source.id,
            SourceDocumentIngestRequest(
                external_id="memo-1",
                filename="memo.txt",
                content="First confidential candidate claim.",
            ),
        )
    with service.authorized_as(integration, "envelope-denied"):
        with pytest.raises(PolicyRefusalError, match="not authorized"):
            service.ingest_source_document(
                source.id,
                SourceDocumentIngestRequest(
                    external_id="memo-2",
                    filename="memo.txt",
                    content="integration must not curate content",
                ),
            )

    entries = service.audit.list_entries(correlation_id="envelope-write", actor_id="curator-1")
    encryption = [entry for entry in entries if entry.event_type == "content_envelope_encryption"]
    assert len(encryption) == 1
    assert encryption[0].payload == {
        "decision": "allowed",
        "protection": "envelope-encrypted",
        "key_ref": "kms://solomon/content/v1",
        "source_id": source.id,
        "document_id": document.id,
        "document_count": 1,
        "candidate_count": len(candidates),
    }
    assert encryption[0].attribution is not None
    assert encryption[0].attribution.actor_id == "curator-1"
    assert encryption[0].attribution.correlation_id == "envelope-write"
    denied = [
        entry
        for entry in service.audit.list_entries(correlation_id="envelope-denied", actor_id="integration-1")
        if entry.event_type == "service_authorization"
    ]
    assert denied[0].payload["decision"] == "denied"

    raw = (tmp_path / "data" / "sources.sqlite3").read_bytes()
    assert b"First confidential candidate claim." not in raw
