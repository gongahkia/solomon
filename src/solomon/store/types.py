# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from solomon.currency.models import CurrencyState, KnowledgeItem


class KnowledgeStoreProtocol(Protocol):
    def close(self) -> None: ...

    def write_item(self, item: KnowledgeItem) -> KnowledgeItem: ...

    def update_item(
        self,
        item: KnowledgeItem,
        *,
        event_type: str = "knowledge_item_updated",
        occurred_at: datetime | None = None,
    ) -> KnowledgeItem: ...

    def get_item(self, item_id: str) -> KnowledgeItem: ...

    def get_many(
        self,
        item_ids: Iterable[str] | None = None,
        *,
        include_states: set[CurrencyState] | None = None,
        matter_id: str | None = None,
        client_id: str | None = None,
    ) -> list[KnowledgeItem]: ...

    def supersede(
        self,
        predecessor_id: str,
        successor: KnowledgeItem,
        *,
        superseded_at: datetime | None = None,
    ) -> tuple[KnowledgeItem, KnowledgeItem]: ...

    def as_of(self, timestamp: datetime) -> list[KnowledgeItem]: ...
