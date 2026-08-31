#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a synthetic, headless dependency-generalization safety scenario."""

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
        "--workspace", type=Path, required=True, help="empty directory for scenario state and artifacts"
    )
    arguments = parser.parse_args()
    workspace = arguments.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SystemExit(f"workspace must be empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    result, snapshot = run(workspace)
    (workspace / "adversarial-dependency-generalization-result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (workspace / "adversarial-dependency-generalization-snapshot.json").write_text(
        json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, sort_keys=True, indent=2))


def run(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    started = time.perf_counter()
    service = _service(workspace)
    promotion = CandidateClaimPromotionRequest(
        by="curator-alpha",
        kind=KnowledgeKind.POSITION,
        source_kind=SourceKind.MATTER_DOC,
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    source = service.register_document_source(
        DocumentSourceRequest(
            name="synthetic challenge evidence", kind=DocumentSourceKind.FILESYSTEM, root_ref="/fixture"
        )
    )
    source_content = "\n\n".join(
        [
            "The direct Alpha position relies on Aster Regulation 7 section 4 for approval.",
            "The review candidate relies on Aster Regulation 7 section 4 pending source verification.",
            "The deferred candidate relies on Aster Regulation 7 section 4 pending source verification.",
        ]
    )
    document, candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="alpha-challenge", filename="alpha-challenge.txt", content=source_content
        ),
    )
    direct_item, rejected_item, deferred_item = [
        service.promote_candidate_claim(candidate.id, promotion) for candidate in candidates
    ]
    direct_suggestion = service.dependency_suggestions(item_id=direct_item.id)[0]
    rejected_suggestion = service.dependency_suggestions(item_id=rejected_item.id)[0]
    deferred_suggestion = service.dependency_suggestions(item_id=deferred_item.id)[0]
    _require(service.graph.get_dependencies(direct_item.id) == [], "no pre-review edge")

    edge = service.confirm_dependency_suggestion(
        direct_suggestion.id,
        DependencySuggestionDecisionRequest(
            by="curator-alpha", matter_id="matter-alpha", reason="source span reviewed"
        ),
    )
    rejected = service.reject_dependency_suggestion(
        rejected_suggestion.id,
        DependencySuggestionDecisionRequest(by="curator-alpha", matter_id="matter-alpha", reason="not adopted"),
    )
    deferred = service.defer_dependency_suggestion(
        deferred_suggestion.id,
        DependencySuggestionDecisionRequest(by="curator-alpha", matter_id="matter-alpha", reason="awaiting evidence"),
    )

    cross_item = _ingest(service, "The team adopts the notice formula. Cedar Code 9 section 3 provides that formula.")
    cross_suggestions = service.dependency_suggestions(item_id=cross_item.id)
    quote_item = _ingest(
        service,
        "The file quotes, ‘Aster Regulation 7 section 4 controls approval.’ "
        "The firm takes no position on that statement.",
    )
    negated_item = _ingest(
        service,
        "The position does not rely on Boreal Rule 2 section 8 because the factual threshold is absent.",
    )
    multi_item = _ingest(
        service,
        "The analysis relies on Aster Regulation 7 section 4 for approval. "
        "Boreal Rule 2 section 8 is listed only as background.",
    )
    ambiguous_item = _ingest(
        service, "The draft says the Regulation may matter without an identified title or section."
    )
    format_base = _ingest(service, "The format check relies on Aster Regulation 7 section 4 for approval.")
    format_variant = _ingest(
        service, "Analysis\n\nThe format check relies on Aster Regulation 7 section 4 for approval."
    )

    unchanged, unchanged_candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="alpha-challenge", filename="alpha-challenge.txt", content=source_content
        ),
    )
    rejected_suppressed = service.suggest_dependencies(DependencySuggestionRequest(item_id=rejected_item.id)) == []
    revised, revised_candidates = service.ingest_source_document(
        source.id,
        SourceDocumentIngestRequest(
            external_id="alpha-challenge",
            filename="alpha-challenge.txt",
            content="Revision two relies on Boreal Rule 2 section 8 for the changed approval path.",
        ),
    )
    revised_item = service.promote_candidate_claim(revised_candidates[0].id, promotion)
    revised_suggestion = service.dependency_suggestions(item_id=revised_item.id)[0]

    bravo_item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="The Bravo position relies on Aster Regulation 7 section 4 for a separate client.",
            source_kind=SourceKind.PARTNER,
            source_ref="fixture://bravo",
            matter_id="matter-bravo",
            client_id="client-bravo",
        )
    )
    bravo_suggestion = service.dependency_suggestions(item_id=bravo_item.id)[0]
    cross_scope_denied = False
    try:
        service.confirm_dependency_suggestion(
            bravo_suggestion.id,
            DependencySuggestionDecisionRequest(by="curator-alpha", matter_id="matter-alpha"),
        )
    except BadRequestError:
        cross_scope_denied = True

    service.register_authority_change(
        "aster-regulation-7-section-4",
        AuthorityChangeRequest(new_version="2026-09", changed_at="2026-09-01T00:00:00+00:00"),
    )
    restarted = _service(workspace)
    pack = restarted.export_audit_pack(workspace / "audit-pack")

    _require(direct_suggestion.decision is SuggestionDecision.PENDING, "direct suggestion starts pending")
    _require(edge.source_suggestion_id == direct_suggestion.id, "confirmation preserves suggestion provenance")
    _require(rejected.decision is SuggestionDecision.REJECTED, "rejection recorded")
    _require(deferred.decision is SuggestionDecision.DEFERRED, "deferral recorded")
    _require(len(cross_suggestions) == 1, "cross-sentence reliance suggested once")
    _require(cross_suggestions[0].source_span == cross_item.content, "cross-sentence evidence reconstructible")
    _require(service.dependency_suggestions(item_id=quote_item.id) == [], "quotation abstains")
    _require(service.dependency_suggestions(item_id=negated_item.id) == [], "negation abstains")
    _require(
        [row.suggested_edge.target_id for row in service.dependency_suggestions(item_id=multi_item.id)]
        == ["aster-regulation-7-section-4"],
        "only the supported authority is suggested",
    )
    _require(service.dependency_suggestions(item_id=ambiguous_item.id) == [], "ambiguous text abstains")
    _require(
        [row.suggested_edge.target_id for row in service.dependency_suggestions(item_id=format_base.id)]
        == [row.suggested_edge.target_id for row in service.dependency_suggestions(item_id=format_variant.id)],
        "heading formatting mutation is target-stable",
    )
    _require(
        unchanged.id == document.id and len(unchanged_candidates) == len(candidates), "unchanged ingestion deduplicates"
    )
    _require(rejected_suppressed, "rejected unchanged evidence remains suppressed")
    _require(revised.version == 2 and revised.previous_version_id == document.id, "revision lineage is retained")
    _require(revised_suggestion.previous_source_document_id == document.id, "revision suggestion links prior version")
    _require(cross_scope_denied, "cross-tenant decision is denied")
    _require(
        bravo_suggestion.id
        not in {
            suggestion.id
            for suggestion in restarted.dependency_suggestions(matter_id="matter-alpha", client_id="client-alpha")
        },
        "cross-tenant suggestion is excluded from alpha queue",
    )
    _require(
        restarted.store.get_item(direct_item.id).currency_state is CurrencyState.STALE_PENDING_REVERIFICATION,
        "confirmed edge stales",
    )
    _require(
        restarted.store.get_item(rejected_item.id).currency_state is CurrencyState.LIVE, "rejected edge remains live"
    )
    _require(
        restarted.store.get_item(deferred_item.id).currency_state is CurrencyState.LIVE, "deferred edge remains live"
    )
    _require(restarted.audit.verify().ok and restarted.audit.verify_pack(pack).ok, "audit journal and pack verify")

    snapshot: dict[str, object] = {
        "schema": "solomon.adversarial_dependency_generalization_proof.snapshot.v1",
        "synthetic_fixture": {"documents": 3, "scopes": 2, "authorities": 3},
        "reference_and_classification": {
            "direct_positive": True,
            "cross_sentence_positive": True,
            "quote_abstains": True,
            "negation_abstains": True,
            "one_of_multiple_authorities_supported": True,
            "ambiguous_abstains": True,
            "heading_mutation_target_stable": True,
        },
        "lifecycle": {
            "pre_review_edges": 0,
            "confirmed": 1,
            "rejected": 1,
            "deferred": 1,
            "unchanged_document_deduplicated": True,
            "rejected_unchanged_evidence_suppressed": True,
            "revision_version": 2,
            "revision_lineage": True,
        },
        "safety": {
            "cross_tenant_decision_denied": True,
            "cross_tenant_queue_excluded": True,
            "confirmed_currency_impacts": 1,
            "pending_rejected_deferred_currency_impacts": 0,
            "audit_pack_verified": True,
        },
    }
    return {
        **snapshot,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "latency_budget_ms": 2_000,
    }, snapshot


def _service(workspace: Path) -> SolomonService:
    return SolomonService(data_dir=workspace / "data", journal_dir=workspace / "journal")


def _ingest(service: SolomonService, content: str) -> object:
    return service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content=content,
            source_kind=SourceKind.MATTER_DOC,
            source_ref=f"fixture://{abs(hash(content))}",
            matter_id="matter-alpha",
            client_id="client-alpha",
        )
    )


def _require(value: bool, label: str) -> None:
    if not value:
        raise RuntimeError(f"proof invariant failed: {label}")


if __name__ == "__main__":
    main()
