# SPDX-License-Identifier: Apache-2.0

"""Legacy source-revision markers remain reconstructible during durable reconciliation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from solomon.api.services.dependency_assertions import GovernedDependencyAssertionLifecycle
from solomon.currency.models import now_utc
from solomon.graph.suggestions import SuggestionDecision


class _LifecycleAssertion(SimpleNamespace):
    def model_copy(self, *, update: dict[str, Any]) -> _LifecycleAssertion:
        values = dict(self.__dict__)
        values.update(update)
        return _LifecycleAssertion(**values)


def _assertion(assertion_id: str, *, document_id: str, needs_reverification: bool = False) -> Any:
    return _LifecycleAssertion(
        id=assertion_id,
        item_id="item-a",
        source_document_id=document_id,
        needs_reverification=needs_reverification,
        state_version=1,
        decision=SuggestionDecision.CONFIRMED,
        suggested_edge=SimpleNamespace(id=f"edge-{assertion_id}"),
        audit_correlation_id=f"correlation-{assertion_id}",
        created_at=now_utc(),
    )


def test_legacy_source_revision_marker_is_idempotent_and_preserves_audit_lineage() -> None:
    current = _assertion("assertion-a", document_id="document-a")
    unrelated = _assertion("assertion-b", document_id="document-other")
    already_marked = _assertion("assertion-c", document_id="document-a", needs_reverification=True)
    updated: list[Any] = []
    audit_payloads: list[dict[str, Any]] = []

    graph: Any = SimpleNamespace(
        list_dependency_suggestions=lambda **filters: [current, unrelated, already_marked]
        if filters.get("source") == "human"
        else [],
        update_dependency_suggestion=lambda assertion: updated.append(assertion),
    )
    def append_audit(event_type: str, payload: dict[str, Any], attribution: Any) -> Any:
        audit_payloads.append({"event_type": event_type, **payload})
        return SimpleNamespace(entry_hash="reverification-audit")

    audit: Any = SimpleNamespace(append=append_audit)
    dependencies: Any = SimpleNamespace(matter_id="matter-a", client_id="client-a")
    unavailable: Any = object()
    lifecycle = GovernedDependencyAssertionLifecycle(
        graph=graph,
        audit=audit,
        currency_cache=unavailable,
        get_item=lambda _: dependencies,
        document_store=unavailable,
        authority_sources=unavailable,
        authority_identifiers=unavailable,
        on_confirmed_edge=lambda _: None,
        schedule_creation=lambda assertion: assertion,
        schedule_confirmation=lambda assertion, request: assertion.suggested_edge,
        schedule_transition=lambda assertion: assertion,
    )

    assert lifecycle.mark_reverification_for_source_revision(
        previous_document_id=None,
        replacement_document_id="document-b",
    ) == []
    marked = lifecycle.mark_reverification_for_source_revision(
        previous_document_id="document-a",
        replacement_document_id="document-b",
    )

    assert [assertion.id for assertion in marked] == ["assertion-a"]
    assert marked[0].needs_reverification is True
    assert marked[0].reverification_audit_id == "reverification-audit"
    assert [entry["event_type"] for entry in audit_payloads] == ["dependency_assertion_reverification_requested"]
    assert audit_payloads[0]["edge_id"] == "edge-assertion-a"
    assert len(updated) == 2
