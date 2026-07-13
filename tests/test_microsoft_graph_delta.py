# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from solomon.contracts import SyncCheckpoint
from solomon.sources.microsoft_graph import MicrosoftGraphDeltaError, MicrosoftGraphDeltaSynchronizer
from solomon.sources.models import DocumentSource, DocumentSourceKind
from solomon.sources.store import SQLiteDocumentStore


@dataclass
class Response:
    status_code: int
    payload: dict[str, Any]

    def json(self) -> dict[str, Any]:
        return self.payload


class Transport:
    def __init__(self, responses: dict[str, list[Response]]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str) -> Response:
        self.calls.append(url)
        return self.responses[url].pop(0)


def _source(store: SQLiteDocumentStore) -> DocumentSource:
    return store.upsert_source(
        DocumentSource(
            id="graph-1",
            name="microsoft 365",
            kind=DocumentSourceKind.MICROSOFT_GRAPH,
            root_ref="https://graph.microsoft.com/v1.0/sites/site-1/drive/root/delta",
        )
    )


def test_graph_delta_paginates_preserves_provenance_and_persists_delta_cursor(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = _source(store)
    root = source.root_ref
    next_url = "https://graph.microsoft.com/next"
    delta_url = "https://graph.microsoft.com/delta-token"
    transport = Transport(
        {
            root: [
                Response(
                    200,
                    {
                        "value": [
                            {
                                "id": "drive-1",
                                "name": "memo.docx",
                                "webUrl": "https://share/memo",
                                "eTag": "v1",
                            }
                        ],
                        "@odata.nextLink": next_url,
                    },
                )
            ],
            next_url: [Response(200, {"value": [{"id": "drive-2", "deleted": {}}], "@odata.deltaLink": delta_url})],
        }
    )

    result = MicrosoftGraphDeltaSynchronizer(store, transport).sync(source.id)

    assert [change.kind for change in result.changes] == ["upsert", "deleted"]
    assert result.changes[0].metadata["etag"] == "v1"
    assert result.checkpoint.cursor == delta_url
    assert store.get_sync_checkpoint(source.id) == result.checkpoint
    assert transport.calls == [root, next_url]


def test_graph_delta_recovers_once_from_expired_cursor_retries_and_rejects_invalid_payload(tmp_path):
    store = SQLiteDocumentStore(tmp_path / "sources.sqlite3")
    source = _source(store)
    expired = "https://graph.microsoft.com/expired"
    store.set_sync_checkpoint(SyncCheckpoint(source_id=source.id, cursor=expired))
    delta_url = "https://graph.microsoft.com/delta-token"
    transport = Transport(
        {
            expired: [Response(410, {})],
            source.root_ref: [Response(503, {}), Response(200, {"value": [], "@odata.deltaLink": delta_url})],
        }
    )

    result = MicrosoftGraphDeltaSynchronizer(store, transport).sync(source.id)

    assert result.resynchronized is True
    assert transport.calls == [expired, source.root_ref, source.root_ref]
    invalid = Transport({delta_url: [Response(200, {"value": "bad", "@odata.deltaLink": delta_url})]})
    store.set_sync_checkpoint(result.checkpoint.model_copy(update={"cursor": delta_url}))
    with pytest.raises(MicrosoftGraphDeltaError, match="value list"):
        MicrosoftGraphDeltaSynchronizer(store, invalid).sync(source.id)
