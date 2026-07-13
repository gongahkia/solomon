# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from solomon.connectors import ConnectorConfiguration, SecretReference, SecretReferenceProvider
from solomon.sources.models import DocumentSource, DocumentSourceKind
from solomon.sources.store import SQLiteDocumentStore


def test_connector_configuration_persists_settings_and_secret_references_without_secret_material(tmp_path):
    configuration = ConnectorConfiguration(
        settings={"drive_id": "shared-knowledge", "recursive": True},
        secret_references={
            "graph_client_secret": SecretReference(
                provider=SecretReferenceProvider.VAULT,
                reference="kv/solomon/microsoft-graph/client-secret",
            )
        },
    )
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = store.upsert_source(
        DocumentSource(
            id="source-1",
            name="microsoft graph",
            kind=DocumentSourceKind.MICROSOFT_GRAPH,
            root_ref="https://graph.microsoft.com/v1.0/sites/site-1",
            config=configuration,
        )
    )
    persisted = sqlite3.connect(store.path).execute("SELECT source_json FROM document_sources").fetchone()[0]

    assert store.get_source(source.id).config == configuration
    assert "kv/solomon/microsoft-graph/client-secret" in persisted
    assert "client-secret-value" not in persisted
    store.close()


@pytest.mark.parametrize(
    "setting",
    [{"api_key": "client-secret-value"}, {"headers": {"Authorization": "Bearer value"}}],
)
def test_connector_configuration_rejects_raw_secret_settings(setting):
    with pytest.raises(ValidationError, match="secret_references"):
        ConnectorConfiguration(settings=setting)
