# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from solomon.api.app import create_app
from solomon.config import Settings, embedding_provider_from_settings
from solomon.contracts import EmbeddingRequest
from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.orchestrator.retrieval import (
    EmbeddingStrategy,
    HashedEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SQLiteRetrievalIndex,
)


def _item() -> KnowledgeItem:
    return KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.POSITION,
        content="structure x under regulation r",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo-1"),
    )


def _vector() -> list[float]:
    return [1.0] + [0.0] * 255


def test_local_hashed_provider_is_pinned_and_batches_deterministically(tmp_path: Path) -> None:
    provider = HashedEmbeddingProvider()
    index = SQLiteRetrievalIndex(tmp_path / "solomon.sqlite3", provider=provider)

    indexed = index.batch_upsert([_item()])
    response = provider.embed(EmbeddingRequest(model="hashed-token-vector:1", texts=["structure x"]))

    assert provider.strategy == EmbeddingStrategy()
    assert indexed[0].embedding_ref == "hashed-token-vector:1"
    assert len(response.vectors) == 1
    assert len(response.vectors[0]) == 256


def test_openai_compatible_provider_uses_embeddings_contract_without_exposing_key(tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"model": "remote-embed", "data": [{"index": 0, "embedding": _vector()}]},
        )

    provider = OpenAICompatibleEmbeddingProvider(
        url="https://embeddings.example.test/v1/embeddings",
        api_key="remote-secret",
        model="remote-embed",
        transport=httpx.MockTransport(handler),
    )
    index = SQLiteRetrievalIndex(tmp_path / "solomon.sqlite3", provider=provider)

    indexed = index.upsert_item(_item())
    results = index.search("structure")

    assert indexed.embedding_ref == "openai-compatible:remote-embed"
    assert [result.item_id for result in results] == ["item-1"]
    assert len(requests) == 2
    assert requests[0].headers["authorization"] == "Bearer remote-secret"
    assert json.loads(requests[0].content) == {
        "model": "remote-embed",
        "input": ["structure x under regulation r"],
        "encoding_format": "float",
        "dimensions": 256,
    }


def test_remote_embedding_settings_require_opt_in_redact_key_and_wire_app(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="explicit opt-in"):
        Settings(
            sku="server",
            server_api_key="server-key",
            embedding_provider="openai-compatible",
            embedding_remote_url="https://embeddings.example.test/v1/embeddings",
            embedding_remote_api_key="remote-secret",
        )
    with pytest.raises(ValueError, match="openai-compatible"):
        Settings(allow_remote_embedding_egress=True)

    settings = Settings(
        sku="server",
        server_api_key="server-key",
        data_dir=tmp_path / "data",
        journal_dir=tmp_path / "journal",
        zero_egress_mode=False,
        embedding_provider="openai-compatible",
        embedding_remote_url="https://embeddings.example.test/v1/embeddings",
        embedding_remote_api_key="remote-secret",
        allow_remote_embedding_egress=True,
    )
    provider = embedding_provider_from_settings(settings)
    app = create_app(settings)
    diagnostics = settings.public_diagnostics()

    assert isinstance(provider, OpenAICompatibleEmbeddingProvider)
    assert isinstance(app.state.service.index.provider, OpenAICompatibleEmbeddingProvider)
    assert diagnostics["embedding_remote_api_key_configured"] is True
    assert "remote-secret" not in json.dumps(diagnostics)
    assert "remote-secret" not in json.dumps(settings.model_dump(mode="json"))
    assert "remote-secret" not in repr(provider.__dict__)
