# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from solomon.api.schemas import SolomonModel
from solomon.currency.engine import evaluate_currency
from solomon.graph.store import GraphStore
from solomon.store.sqlite import SQLiteKnowledgeStore


class CurrencyReport(SolomonModel):
    matter_id: str | None
    client_id: str | None
    items: list[dict[str, Any]]


def currency_report(
    *,
    store: SQLiteKnowledgeStore,
    graph: GraphStore,
    matter_id: str | None = None,
    client_id: str | None = None,
) -> CurrencyReport:
    items = []
    for item in store.get_many(matter_id=matter_id, client_id=client_id):
        items.append(
            {
                "item_id": item.id,
                "kind": item.kind.value,
                "currency": evaluate_currency(item).model_dump(mode="json"),
                "dependencies": [edge.model_dump(mode="json") for edge in graph.get_dependencies(item.id)],
                "credence_tier": item.credence_tier.value,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
            }
        )
    return CurrencyReport(matter_id=matter_id, client_id=client_id, items=items)

