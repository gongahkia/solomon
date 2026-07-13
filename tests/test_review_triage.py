# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

from solomon.currency.models import KnowledgeItem, KnowledgeKind, Provenance, SourceKind
from solomon.workflow.models import AuthorityChangeEvent, ReviewTaskPriority, ReviewTaskState
from solomon.workflow.triage import DeterministicReviewTriage, ReviewTriageRule


def test_configured_triage_is_deterministic_and_only_creates_open_review_obligations():
    timestamp = datetime(2026, 7, 13, tzinfo=timezone.utc)
    item = KnowledgeItem(
        id="item-1",
        kind=KnowledgeKind.HOUSE_VIEW,
        content="Structure X is compliant.",
        provenance=Provenance(source_kind=SourceKind.PARTNER, source_ref="memo-1"),
        valid_from=timestamp,
        ingested_at=timestamp,
    )
    event = AuthorityChangeEvent(
        id="event-1",
        source_id="official-gazette",
        idempotency_key="regulation-r-12:v3",
        authority_id="regulation-r-12",
        new_version="v3",
        changed_at=timestamp,
    )
    triage = DeterministicReviewTriage(
        [
            ReviewTriageRule(
                id="fallback",
                order=10,
                priority=ReviewTaskPriority.NORMAL,
            ),
            ReviewTriageRule(
                id="official-house-view",
                order=1,
                source_id="official-gazette",
                item_kind=KnowledgeKind.HOUSE_VIEW,
                priority=ReviewTaskPriority.URGENT,
                recommended_reviewer_id="lawyer-a",
            ),
        ]
    )

    first = triage.create_task(event, item)
    repeated = triage.create_task(event, item)

    assert first.priority is ReviewTaskPriority.URGENT
    assert first.recommended_reviewer_id == "lawyer-a"
    assert first.reviewer_id is None
    assert first.state is ReviewTaskState.OPEN
    assert first.model_dump(exclude={"id", "created_at", "updated_at"}) == repeated.model_dump(
        exclude={"id", "created_at", "updated_at"}
    )
