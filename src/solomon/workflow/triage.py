# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeItem, KnowledgeKind
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority


class ReviewTriageRule(SolomonModel):
    id: str = Field(min_length=1)
    order: int = Field(ge=0)
    source_id: str | None = None
    authority_id: str | None = None
    item_kind: KnowledgeKind | None = None
    priority: ReviewTaskPriority
    recommended_reviewer_id: str | None = None

    def matches(self, event: AuthorityChangeEvent, item: KnowledgeItem) -> bool:
        return (
            (self.source_id is None or self.source_id == event.source_id)
            and (self.authority_id is None or self.authority_id == event.authority_id)
            and (self.item_kind is None or self.item_kind is item.kind)
        )


class DeterministicReviewTriage:
    def __init__(self, rules: list[ReviewTriageRule]) -> None:
        self.rules = sorted(rules, key=lambda rule: (rule.order, rule.id))

    def create_task(self, event: AuthorityChangeEvent, item: KnowledgeItem) -> ReviewTask:
        rule = next((candidate for candidate in self.rules if candidate.matches(event, item)), None)
        priority = rule.priority if rule is not None else ReviewTaskPriority.NORMAL
        reviewer_id = rule.recommended_reviewer_id if rule is not None else None
        return ReviewTask(
            event_id=event.id,
            item_id=item.id,
            priority=priority,
            reason=f"authority {event.authority_id} changed to {event.new_version}",
            recommended_reviewer_id=reviewer_id,
        )


__all__ = ["DeterministicReviewTriage", "ReviewTriageRule"]
