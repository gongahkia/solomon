# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import DependencySuggestion, SuggestionDecision
from solomon.store.types import KnowledgeStoreProtocol


class DependencyGraphProtocol(Protocol):
    def close(self) -> None: ...

    def add_dependency(self, edge: DependencyEdge) -> DependencyEdge: ...

    def add_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion: ...

    def update_dependency_suggestion(self, suggestion: DependencySuggestion) -> DependencySuggestion: ...

    def get_dependency_suggestion(self, suggestion_id: str) -> DependencySuggestion: ...

    def list_dependency_suggestions(
        self,
        *,
        item_id: str | None = None,
        decision: SuggestionDecision | None = None,
        limit: int = 100,
    ) -> list[DependencySuggestion]: ...

    def close_dependency(self, edge_id: str, *, valid_to: datetime) -> DependencyEdge: ...

    def get_edge(self, edge_id: str) -> DependencyEdge: ...

    def get_dependencies(self, item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]: ...

    def get_dependents(self, authority_or_item_id: str, *, at: datetime | None = None) -> list[DependencyEdge]: ...

    def impact_edges(self, authority_or_item_id: str) -> list[DependencyEdge]: ...

    def centrality(self, item_or_authority_ids: Iterable[str] | None = None) -> dict[str, int]: ...

    def subgraph_for_items(self, item_ids: Iterable[str]) -> list[DependencyEdge]: ...

    def subgraph_for_scope(
        self,
        *,
        store: KnowledgeStoreProtocol,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[DependencyEdge]: ...
