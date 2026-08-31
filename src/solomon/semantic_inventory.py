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
    """Return a content-redacting checkpoint comparison across durable components.

    Coordinated checkpoint and recovery append operational audit records around
    the captured state. Those records are verified separately through the
    retained audit pack and are excluded here so a preserved checkpoint can be
    compared to its restored domain state without treating recovery evidence
    as source-state drift.
    """

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
    source_records = _source_records(service.document_store.path)
    audit_entries = [
        entry.model_dump(mode="json")
        for entry in service.audit.list_entries()
        if entry.event_type
        not in {
            "deployment_backup_started",
            "deployment_backup_completed",
            "deployment_restore_started",
            "deployment_restore_completed",
        }
    ]
    components = {
        "knowledge_items": _summary(items),
        "graph_edges": _summary(edges),
        "assertions": _summary(assertions),
        "operations": _summary(operations),
        "source_documents": _summary(source_records["documents"]),
        "source_changes": _summary(source_records["changes"]),
        "source_candidates": _summary(source_records["candidates"]),
        "source_registrations": _summary(source_records["sources"]),
        "local_sqlite_state": _summary(_sqlite_state_records(service.document_store.path.parent)),
        "local_metadata": _summary(_metadata_records(service.document_store.path.parent)),
        "audit_correlation": _summary(audit_entries),
    }
    return {"schema_id": "solomon.semantic_inventory.v2", "components": components}


def _source_records(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        return {"documents": [], "changes": [], "candidates": [], "sources": []}
    with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as database:
        return {
            "documents": _json_column(database, "source_documents", "document_json"),
            "changes": _json_column(database, "source_change_events", "event_json"),
            "candidates": _json_column(database, "candidate_claims", "candidate_json"),
            "sources": _json_column(database, "document_sources", "source_json"),
        }


def _json_column(database: sqlite3.Connection, table: str, column: str) -> list[dict[str, Any]]:
    available = {
        str(row[0])
        for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    if table not in available:
        return []
    return [json.loads(row[0]) for row in database.execute(f"SELECT {column} FROM {table}")]  # noqa: S608


def _sqlite_state_records(data_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(data_dir.rglob("*.sqlite3")):
        relative = path.relative_to(data_dir).as_posix()
        if path.is_symlink() or not path.is_file():
            records.append({"path": relative, "state": "unsafe"})
            continue
        with sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True) as database:
            database.row_factory = sqlite3.Row
            tables = [
                str(row[0])
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            for table in tables:
                rows = [
                    {key: _json_value(value) for key, value in dict(row).items()}
                    for row in database.execute(f'SELECT * FROM "{table}"')  # noqa: S608
                ]
                records.append(
                    {
                        "path": relative,
                        "table": table,
                        "rows": sorted(rows, key=_canonical_json),
                    }
                )
    return records


def _metadata_records(data_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(data_dir.rglob("*.json")):
        relative = path.relative_to(data_dir)
        if path.is_symlink() or ".solomon-maintenance" in relative.name:
            continue
        records.append({"path": relative.as_posix(), "content": json.loads(path.read_text(encoding="utf-8"))})
    return records


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _summary(records: list[Any]) -> dict[str, Any]:
    encoded = _canonical_json(records).encode()
    return {"count": len(records), "sha256": hashlib.sha256(encoded).hexdigest()}
