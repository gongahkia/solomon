# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from solomon.api.service import SolomonService
from solomon.api.service_models import (
    AuthorityEventRequest,
    DependencyRequest,
    IngestRequest,
    ReviewTaskAssignmentRequest,
    ReviewTaskResolutionRequest,
    ReviewTaskStartRequest,
    VerificationRequest,
)
from solomon.currency.engine import VerificationOutcome
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeType
from solomon.workflow.models import AuthorityChangeEvent, ReviewTask, ReviewTaskPriority, ReviewTaskState
from solomon.workflow.store import AuthorityEventNotFoundError, ReviewTaskNotFoundError, SQLiteWorkflowStore


def test_authority_event_creates_idempotent_review_task_and_requires_verification(tmp_path):
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.HOUSE_VIEW,
            content="Structure X is compliant under Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-1",
            author="Partner A",
        )
    )
    service.add_dependency(
        DependencyRequest(
            source_id=item.id,
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
        )
    )
    request = AuthorityEventRequest(
        source_id="official-feed",
        idempotency_key="event-1",
        authority_id="reg-r-12",
        new_version="2026-07-13",
        changed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        evidence_url="https://example.test/reg-r-12",
    )

    result = service.register_authority_event(request)
    duplicate = service.register_authority_event(request)
    task_id = result["review_tasks"][0]["id"]

    assert result["duplicate"] is False
    assert result["review_tasks"][0]["priority"] == "urgent"
    assert duplicate["duplicate"] is True
    assert len(service.review_tasks()) == 1

    assigned = service.assign_review_task(
        task_id,
        ReviewTaskAssignmentRequest(reviewer_id="lawyer-a", assigned_by="curator-a"),
    )
    assert assigned.state.value == "assigned"
    started = service.start_review_task(task_id, ReviewTaskStartRequest(reviewer_id="lawyer-a"))
    assert started.state.value == "in_review"
    resolved = service.resolve_review_task(
        task_id,
        ReviewTaskResolutionRequest(
            reviewer_id="lawyer-a",
            verification=VerificationRequest(
                by="lawyer-a",
                outcome=VerificationOutcome.REAFFIRM,
                basis="reviewed official change",
                source_ref="https://example.test/reg-r-12",
            ),
        ),
    )
    assert resolved.state.value == "resolved"
    assert service.evaluate_currency(item.id)["currency_state"] == "Live"


def test_workflow_store_transitions_filters_and_errors(tmp_path):
    store = SQLiteWorkflowStore(tmp_path / "workflow.sqlite3")
    event = AuthorityChangeEvent(
        source_id="feed-a",
        idempotency_key="key-a",
        authority_id="reg-a",
        new_version="v2",
        changed_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
    )
    recorded, created = store.record_authority_event(event)
    duplicate, duplicate_created = store.record_authority_event(event)
    task = store.create_review_task(
        ReviewTask(event_id=event.id, item_id="item-a", priority=ReviewTaskPriority.HIGH, reason="authority moved")
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate == recorded
    assert store.create_review_task(task) == task
    assert store.list_review_tasks(state=ReviewTaskState.OPEN) == [task]
    assigned = store.assign(task.id, reviewer_id="reviewer-a", assigned_by="curator-a")
    assert store.list_review_tasks(reviewer_id="reviewer-a", state=ReviewTaskState.ASSIGNED) == [assigned]
    with pytest.raises(ValueError, match="assigned reviewer"):
        store.start(task.id, reviewer_id="reviewer-b")
    started = store.start(task.id, reviewer_id="reviewer-a")
    resolved = store.resolve(task.id, reviewer_id="reviewer-a")
    assert started.state is ReviewTaskState.IN_REVIEW
    assert resolved.state is ReviewTaskState.RESOLVED
    with pytest.raises(ValueError, match="cannot be assigned"):
        store.assign(task.id, reviewer_id="reviewer-b", assigned_by="curator-a")
    with pytest.raises(AuthorityEventNotFoundError):
        store.get_authority_event("missing")
    with pytest.raises(ReviewTaskNotFoundError):
        store.get_review_task("missing")
