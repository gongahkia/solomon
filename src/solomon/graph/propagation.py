# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections import deque
from datetime import datetime

from solomon.currency.models import CurrencyState, now_utc
from solomon.currency.verification import (
    VerificationLifecycleEvent,
    VerificationLifecycleState,
    append_verification_event,
)
from solomon.graph.models import ImpactResult, StalenessReason
from solomon.graph.types import DependencyGraphProtocol
from solomon.store.sqlite import ItemNotFoundError
from solomon.store.types import KnowledgeStoreProtocol


class CurrencyPropagator:
    def __init__(self, *, graph: DependencyGraphProtocol, store: KnowledgeStoreProtocol) -> None:
        self.graph = graph
        self.store = store

    def propagate_dependency_change(
        self,
        changed_dependency_id: str,
        *,
        changed_at: datetime | None = None,
        reason: str,
        collect_reasons: bool = True,
        record_verification_events: bool = True,
        record_staleness_metadata: bool = True,
    ) -> ImpactResult:
        timestamp = changed_at or now_utc()
        queue: deque[str] = deque([changed_dependency_id])
        visited_dependencies: set[str] = set()
        stale_item_ids: list[str] = []
        stale_item_id_set: set[str] = set()
        reasons: dict[str, list[StalenessReason]] = {}

        while queue:
            dependency_id = queue.popleft()
            if dependency_id in visited_dependencies:
                continue
            visited_dependencies.add(dependency_id)

            for edge in self.graph.get_dependents(dependency_id):
                item_id = edge.source_id
                try:
                    item = self.store.get_item(item_id)
                except ItemNotFoundError:
                    continue
                if item.currency_state is CurrencyState.RETIRED:
                    continue
                staleness: StalenessReason | None = None
                metadata = item.metadata
                if record_staleness_metadata or collect_reasons:
                    staleness = StalenessReason(
                        dependency_id=dependency_id,
                        changed_at=timestamp,
                        reason=reason,
                        edge_id=edge.id,
                    )
                if record_staleness_metadata:
                    if staleness is None:
                        raise RuntimeError("staleness reason required when recording propagation metadata")
                    existing = list(item.metadata.get("staleness_reasons", []))
                    existing.append(staleness.model_dump(mode="json"))
                    metadata = {**item.metadata, "staleness_reasons": existing}
                updated = item.model_copy(
                    update={
                        "currency_state": CurrencyState.STALE_PENDING_REVERIFICATION,
                        "metadata": metadata,
                    }
                )
                if record_verification_events:
                    updated = append_verification_event(
                        updated,
                        VerificationLifecycleEvent(
                            item_id=item_id,
                            state=VerificationLifecycleState.REQUESTED,
                            actor_id="system",
                            occurred_at=timestamp,
                            basis=reason,
                            source_ref=dependency_id,
                        ),
                    )
                self.store.update_item(updated, event_type="knowledge_item_stale_flagged", occurred_at=timestamp)
                if item_id not in stale_item_id_set:
                    stale_item_ids.append(item_id)
                    stale_item_id_set.add(item_id)
                if collect_reasons:
                    if staleness is None:
                        raise RuntimeError("staleness reason required when collecting propagation reasons")
                    reasons.setdefault(item_id, []).append(staleness)
                queue.append(item_id)

        return ImpactResult(
            changed_dependency_id=changed_dependency_id,
            stale_item_ids=stale_item_ids,
            reasons=reasons,
        )

    def impact_query(self, authority_or_item_id: str, *, as_of: datetime | None = None) -> ImpactResult:
        reasons: dict[str, list[StalenessReason]] = {}
        stale_item_ids: list[str] = []
        stale_item_id_set: set[str] = set()
        timestamp = as_of or now_utc()
        queue: deque[str] = deque([authority_or_item_id])
        visited_dependencies: set[str] = set()
        while queue:
            dependency_id = queue.popleft()
            if dependency_id in visited_dependencies:
                continue
            visited_dependencies.add(dependency_id)
            for edge in self.graph.get_dependents(dependency_id):
                item_id = edge.source_id
                if item_id not in stale_item_id_set:
                    stale_item_ids.append(item_id)
                    stale_item_id_set.add(item_id)
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
