# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from solomon.currency.models import KnowledgeItem
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion


def events_to_state(rows: Iterable[Any]) -> list[KnowledgeItem]:
    state: dict[str, KnowledgeItem] = {}
    for row in rows:
        payload = json.loads(payload_json_text(row_value(row, "payload_json")))
        event_type = str(row_value(row, "event_type"))
        if event_type in {
            "knowledge_item_written",
            "knowledge_item_updated",
            "knowledge_item_stale_flagged",
            "knowledge_item_indexed",
            "knowledge_item_contested",
            "knowledge_item_affirmed",
            "knowledge_item_correction_affirmed",
            "knowledge_item_pinned",
        }:
            item = KnowledgeItem.model_validate(payload["item"])
            state[item.id] = item
        elif event_type == "knowledge_item_superseded":
            predecessor = KnowledgeItem.model_validate(payload["predecessor"])
            successor = KnowledgeItem.model_validate(payload["successor"])
            state[predecessor.id] = predecessor
            state[successor.id] = successor
    return sorted(state.values(), key=lambda item: (item.ingested_at, item.id))


def item_from_json(value: Any) -> KnowledgeItem:
    if isinstance(value, str):
        return KnowledgeItem.model_validate_json(value)
    return KnowledgeItem.model_validate(value)


def edge_from_json(value: Any) -> DependencyEdge:
    if isinstance(value, str):
        return DependencyEdge.model_validate_json(value)
    return DependencyEdge.model_validate(value)


def suggestion_from_json(value: Any) -> DependencySuggestion:
    if isinstance(value, str):
        return DependencySuggestion.model_validate_json(value)
    return DependencySuggestion.model_validate(value)


def payload_json_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def row_value(row: Any, key: str) -> Any:
    return row[key]
