# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import deque
from datetime import datetime

from solomon.currency.models import CurrencyState, now_utc
from solomon.graph.models import ImpactResult, StalenessReason
from solomon.graph.store import GraphStore
from solomon.store.sqlite import ItemNotFoundError, SQLiteKnowledgeStore


class CurrencyPropagator:
    def __init__(self, *, graph: GraphStore, store: SQLiteKnowledgeStore) -> None:
        self.graph = graph
        self.store = store

    def propagate_dependency_change(
        self,
        changed_dependency_id: str,
        *,
        changed_at: datetime | None = None,
        reason: str,
    ) -> ImpactResult:
        timestamp = changed_at or now_utc()
        queue: deque[str] = deque([changed_dependency_id])
        visited_dependencies: set[str] = set()
        stale_item_ids: list[str] = []
        reasons: dict[str, list[StalenessReason]] = {}

        while queue:
            dependency_id = queue.popleft()
            if dependency_id in visited_dependencies:
                continue
            visited_dependencies.add(dependency_id)

            for edge in self.graph.get_dependents(dependency_id):
                item_id = edge.source_id
                staleness = StalenessReason(
                    dependency_id=dependency_id,
                    changed_at=timestamp,
                    reason=reason,
                    edge_id=edge.id,
                )
                try:
                    item = self.store.get_item(item_id)
                except ItemNotFoundError:
                    continue
                existing = list(item.metadata.get("staleness_reasons", []))
                existing.append(staleness.model_dump(mode="json"))
                updated = item.model_copy(
                    update={
                        "currency_state": CurrencyState.STALE_PENDING_REVERIFICATION,
                        "metadata": {**item.metadata, "staleness_reasons": existing},
                    }
                )
                self.store.update_item(updated, event_type="knowledge_item_stale_flagged", occurred_at=timestamp)
                if item_id not in stale_item_ids:
                    stale_item_ids.append(item_id)
                reasons.setdefault(item_id, []).append(staleness)
                queue.append(item_id)

        return ImpactResult(
            changed_dependency_id=changed_dependency_id,
            stale_item_ids=stale_item_ids,
            reasons=reasons,
        )

    def impact_query(self, authority_or_item_id: str) -> ImpactResult:
        reasons: dict[str, list[StalenessReason]] = {}
        stale_item_ids: list[str] = []
        timestamp = now_utc()
        queue: deque[str] = deque([authority_or_item_id])
        visited_dependencies: set[str] = set()
        while queue:
            dependency_id = queue.popleft()
            if dependency_id in visited_dependencies:
                continue
            visited_dependencies.add(dependency_id)
            for edge in self.graph.get_dependents(dependency_id):
                item_id = edge.source_id
                if item_id not in stale_item_ids:
                    stale_item_ids.append(item_id)
                reasons.setdefault(item_id, []).append(
                    StalenessReason(
                        dependency_id=dependency_id,
                        changed_at=timestamp,
                        reason="impact query candidate: dependency has current or transitive dependents",
                        edge_id=edge.id,
                    )
                )
                queue.append(item_id)
        return ImpactResult(
            changed_dependency_id=authority_or_item_id,
            stale_item_ids=stale_item_ids,
            reasons=reasons,
        )
