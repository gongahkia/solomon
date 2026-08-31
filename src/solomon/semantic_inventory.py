# SPDX-License-Identifier: Apache-2.0

"""Stable, content-redacting semantic inventory for recovery comparison."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from solomon.api.service import SolomonService


def semantic_inventory(service: SolomonService) -> dict[str, Any]:
    """Return deterministic component counts and hashes without returning source contents."""

    items = [item.model_dump(mode="json") for item in service.store.get_many()]
    item_ids = [item["id"] for item in items]
    edges = [edge.model_dump(mode="json") for edge in service.graph.subgraph_for_items(item_ids)]
    assertions = [assertion.model_dump(mode="json") for assertion in service.dependency_assertions(limit=10_000)]
    operations = [
        {
            "operation": operation.model_dump(mode="json"),
            "history": [entry.model_dump(mode="json") for entry in service.operation_store.history(operation.id)],
        }
        for operation in service.operation_store.list(limit=10_000)
    ]
    documents, changes = _source_records(service.document_store.path)
    components = {
        "knowledge_items": _summary(items),
        "graph_edges": _summary(edges),
        "assertions": _summary(assertions),
        "operations": _summary(operations),
        "source_documents": _summary(documents),
        "source_changes": _summary(changes),
    }
    return {"schema_id": "solomon.semantic_inventory.v1", "components": components}


def _source_records(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not path.is_file():
        return [], []
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as database:
        documents = [json.loads(row[0]) for row in database.execute("SELECT document_json FROM source_documents")]
        changes = [json.loads(row[0]) for row in database.execute("SELECT event_json FROM source_change_events")]
    return documents, changes


def _summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    encoded = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    return {"count": len(records), "sha256": hashlib.sha256(encoded).hexdigest()}
