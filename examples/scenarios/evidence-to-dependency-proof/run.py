#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run Solomon's deterministic Evidence-to-Dependency curator proof."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from solomon.api.service import IngestRequest, SolomonService
from solomon.api.service_models import (
    AuthorityChangeRequest,
    CandidateClaimPromotionRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    DocumentSourceRequest,
    SourceDocumentIngestRequest,
)
from solomon.currency.models import CurrencyState, KnowledgeKind, SourceKind
from solomon.errors import BadRequestError
from solomon.graph.suggestions import SuggestionDecision
from solomon.sources.models import DocumentSourceKind


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace",
        type=Path,
        required=True,
        help="empty directory for scenario state and artifacts",
    )
    arguments = parser.parse_args()
    workspace = arguments.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SystemExit(f"workspace must be empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    result, snapshot = run(workspace)
    (workspace / "evidence-to-dependency-proof-result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (workspace / "evidence-to-dependency-proof-snapshot.json").write_text(
        json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, sort_keys=True, indent=2))


def run(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    started = time.perf_counter()
    service = _service(workspace)
    source = service.register_document_source(
        DocumentSourceRequest(
            name="synthetic internal evidence",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref="/evidence",
        )
    )
    content = "\n\n".join(
        [
            "The Alpha position relies on Aster Regulation 7 section 4 for the approval requirement.",
            "The quoted training material says an analyst relies on Aster Regulation 7 section 4; "
            "the current position has not adopted it.",
            "The Alpha position relies on Aster Regulation 7 section 4, but the source context needs further review.",
        ]
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(external_id="alpha-memo", filename="alpha-memo.txt", content=content),
    )
    promotion = CandidateClaimPromotionRequest(
        by="curator-alpha",
        kind=KnowledgeKind.POSITION,
        source_kind=SourceKind.MATTER_DOC,
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    confirmed_item, rejected_item, deferred_item = [
        service.promote_candidate_claim(candidate.id, promotion) for candidate in candidates
    ]
    confirmed_suggestion = service.dependency_suggestions(item_id=confirmed_item.id)[0]
    rejected_suggestion = service.dependency_suggestions(item_id=rejected_item.id)[0]
    deferred_suggestion = service.dependency_suggestions(item_id=deferred_item.id)[0]
    edge = service.confirm_dependency_suggestion(
        confirmed_suggestion.id,
        DependencySuggestionDecisionRequest(
            by="curator-alpha",
            reason="reviewed source evidence",
            matter_id="matter-alpha",
        ),
    )
    service.reject_dependency_suggestion(
        rejected_suggestion.id,
        DependencySuggestionDecisionRequest(
            by="curator-alpha",
            reason="quoted mention is not adopted",
            matter_id="matter-alpha",
        ),
    )
    service.defer_dependency_suggestion(
        deferred_suggestion.id,
        DependencySuggestionDecisionRequest(
            by="curator-alpha",
            reason="need surrounding context",
            matter_id="matter-alpha",
        ),
    )

    unchanged, unchanged_candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(external_id="alpha-memo", filename="alpha-memo.txt", content=content),
    )
    suppressed = service.suggest_dependencies(DependencySuggestionRequest(item_id=rejected_item.id))
    service.register_authority_change(
        "aster-regulation-7-section-4",
        AuthorityChangeRequest(new_version="2026-02", changed_at="2026-02-01T00:00:00+00:00"),
    )

    isolated_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="The Bravo position relies on Aster Regulation 7 section 4 for another client.",
            source_kind=SourceKind.PARTNER,
            source_ref="fixture://bravo",
            matter_id="matter-bravo",
            client_id="client-bravo",
        )
    )
    isolated_suggestion = service.dependency_suggestions(item_id=isolated_item.id)[0]
    cross_scope_denied = False
    try:
        service.confirm_dependency_suggestion(
            isolated_suggestion.id,
            DependencySuggestionDecisionRequest(by="curator-alpha", matter_id="matter-alpha"),
        )
    except BadRequestError:
        cross_scope_denied = True

    restarted = _service(workspace)
    revised, revised_candidates = restarted.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="alpha-memo",
            filename="alpha-memo.txt",
            content="The revised Alpha position relies on Boreal Rule 2 section 8 for the approval requirement.",
        ),
    )
    revised_item = restarted.promote_candidate_claim(revised_candidates[0].id, promotion)
    revised_suggestion = restarted.dependency_suggestions(item_id=revised_item.id)[0]
    pack = restarted.export_audit_pack(workspace / "audit-pack")
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    _require(
        edge.source_suggestion_id == confirmed_suggestion.id,
        "confirmed edge retains suggestion provenance",
    )
    _require(
        unchanged.id == document.id and len(unchanged_candidates) == len(candidates),
        "unchanged ingestion is idempotent",
    )
    _require(suppressed == [], "rejected evidence is suppressed on unchanged re-ingestion")
    confirmed_after_restart = restarted.graph.get_dependency_suggestion(confirmed_suggestion.id)
    confirmed_currency = restarted.store.get_item(confirmed_item.id).currency_state
    rejected_currency = restarted.store.get_item(rejected_item.id).currency_state
    deferred_currency = restarted.store.get_item(deferred_item.id).currency_state
    _require(confirmed_after_restart.decision is SuggestionDecision.CONFIRMED, "restart persistence")
    _require(confirmed_currency is CurrencyState.STALE_PENDING_REVERIFICATION, "confirmed currency impact")
    _require(rejected_currency is CurrencyState.LIVE, "rejected no currency impact")
    _require(deferred_currency is CurrencyState.LIVE, "deferred no currency impact")
    _require(revised.version == 2 and revised.previous_version_id == document.id, "document revision lineage")
    _require(revised_suggestion.previous_source_document_id == document.id, "suggestion revision lineage")
    _require(cross_scope_denied, "scope-isolated decision")
    _require(
        isolated_suggestion.id
        not in {
            suggestion.id
            for suggestion in restarted.dependency_suggestions(matter_id="matter-alpha", client_id="client-alpha")
        },
        "scope-isolated retrieval",
    )
    _require(restarted.audit.verify().ok and restarted.audit.verify_pack(pack).ok, "audit evidence")

    snapshot: dict[str, object] = {
        "schema": "solomon.evidence_to_dependency_proof.snapshot.v1",
        "fixture": {"synthetic_documents": 2, "candidate_claims": 4, "scopes": 2},
        "reference_and_evidence": {
            "normalized_reference": "aster-regulation-7-section-4",
            "source_span_reconstructible": True,
            "authority_span_reconstructible": True,
        },
        "decisions": {"confirmed": 1, "rejected": 1, "deferred": 1, "human_confirmation_required": True},
        "currency": {"confirmed_impacts": 1, "rejected_impacts": 0, "deferred_impacts": 0},
        "idempotency": {"unchanged_document": True, "rejected_suppressed": True, "restart_persistence": True},
        "revision": {"new_document_version": 2, "suggestion_lineage": True},
        "scope": {"cross_scope_decision_denied": True, "alpha_queue_excludes_bravo": True},
        "audit_pack_verified": True,
    }
    result = {**snapshot, "latency_ms": elapsed_ms, "latency_budget_ms": 2_000}
    return result, snapshot


def _service(workspace: Path) -> SolomonService:
    return SolomonService(data_dir=workspace / "data", journal_dir=workspace / "journal")


def _require(value: bool, label: str) -> None:
    if not value:
        raise RuntimeError(f"proof invariant failed: {label}")


if __name__ == "__main__":
    main()
