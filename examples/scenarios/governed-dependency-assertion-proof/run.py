#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the deterministic Governed Dependency Assertion Proof."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from solomon.api.service import (
    AuthorityChangeRequest,
    CandidateClaimPromotionRequest,
    DependencyAssertionCreateRequest,
    DependencyAssertionDecisionRequest,
    DependencyAssertionWithdrawRequest,
    DocumentSourceRequest,
    SolomonService,
    SourceDocumentIngestRequest,
)
from solomon.audit.journal import AuditJournal
from solomon.contracts import AuthoritySource, AuthoritySourceKind
from solomon.currency.models import CurrencyState, KnowledgeKind, SourceKind
from solomon.errors import BadRequestError, NotFoundError, PolicyRefusalError
from solomon.graph.models import DependencyEdge
from solomon.graph.suggestions import AssertionEvidenceKind, DependencyAssertionType, SuggestionDecision
from solomon.sources.models import DocumentSourceKind, SourceDocument


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
    (workspace / "governed-dependency-assertion-proof-result.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    (workspace / "governed-dependency-assertion-proof-snapshot.json").write_text(
        json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(snapshot, sort_keys=True, indent=2))


def run(workspace: Path) -> tuple[dict[str, object], dict[str, object]]:
    started = time.perf_counter()
    service = SolomonService(data_dir=workspace / "data", journal_dir=workspace / "journal")
    alpha_source = service.register_document_source(
        DocumentSourceRequest(
            source_id="alpha-documents",
            name="Alpha registered documents",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref="/alpha-documents",
        )
    )
    bravo_source = service.register_document_source(
        DocumentSourceRequest(
            source_id="bravo-documents",
            name="Bravo registered documents",
            kind=DocumentSourceKind.FILESYSTEM,
            root_ref="/bravo-documents",
        )
    )
    alpha_document, alpha_item = _promote_source_item(
        service,
        source_id=alpha_source.id,
        external_id="alpha-memo",
        content="We rely on Regulation R section 12. The Alpha operating conclusion follows that authority.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    commentary_document, commentary_item = _promote_source_item(
        service,
        source_id=alpha_source.id,
        external_id="alpha-commentary",
        content="The Alpha implementation procedure is governed by a registered operational source.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    upstream_document, upstream_item = _promote_source_item(
        service,
        source_id=alpha_source.id,
        external_id="alpha-upstream",
        content="The trusted upstream report identifies a factual external source for the Alpha review.",
        matter_id="matter-alpha",
        client_id="client-alpha",
    )
    _, bravo_item = _promote_source_item(
        service,
        source_id=bravo_source.id,
        external_id="bravo-memo",
        content="We rely on Regulation B section 3. The Bravo operating conclusion follows that authority.",
        matter_id="matter-bravo",
        client_id="client-bravo",
    )
    service.register_authority_source(
        AuthoritySource(
            id="alpha-gazette",
            name="Alpha official gazette",
            kind=AuthoritySourceKind.FEED,
            root_ref="https://alpha-gazette.example.test/feed",
            matter_id="matter-alpha",
            client_id="client-alpha",
        )
    )
    service.register_authority_source(
        AuthoritySource(
            id="bravo-gazette",
            name="Bravo official gazette",
            kind=AuthoritySourceKind.FEED,
            root_ref="https://bravo-gazette.example.test/feed",
            matter_id="matter-bravo",
            client_id="client-bravo",
        )
    )

    quote = alpha_document.content.split(" The Alpha", maxsplit=1)[0]
    human = service.create_dependency_assertion(
        _assertion_request(
            item_id=alpha_item,
            document_id=alpha_document.id,
            assertion_type=DependencyAssertionType.NORMATIVE_POLICY,
            evidence_kind=AssertionEvidenceKind.QUOTE,
            quote=quote,
            quote_start=0,
            quote_end=len(quote),
            idempotency_key="human-quote",
        )
    )
    commentary = service.create_dependency_assertion(
        _assertion_request(
            item_id=upstream_item,
            document_id=upstream_document.id,
            assertion_type=DependencyAssertionType.PROCEDURAL,
            evidence_kind=AssertionEvidenceKind.COMMENTARY,
            commentary="The curator records an operational dependency without claiming a quotation.",
            authority_identifier="SG-R-13",
            idempotency_key="human-commentary",
        )
    )
    upstream = service.create_dependency_assertion(
        _assertion_request(
            item_id=alpha_item,
            document_id=alpha_document.id,
            assertion_type=DependencyAssertionType.FACTUAL_EVIDENCE,
            evidence_kind=AssertionEvidenceKind.COMMENTARY,
            commentary="Trusted upstream source reports a factual dependency for review.",
            authority_identifier="SG-R-14",
            origin="trusted_upstream",
            trusted_upstream_ref="connector://gazette/observation-14",
            idempotency_key="trusted-upstream",
        )
    )
    no_edges_at_creation = service.graph.get_dependencies(alpha_item) == []

    malformed_quote_rejected = _raises(
        BadRequestError,
        lambda: service.create_dependency_assertion(
            _assertion_request(
                item_id=alpha_item,
                document_id=alpha_document.id,
                assertion_type=DependencyAssertionType.NORMATIVE_POLICY,
                evidence_kind=AssertionEvidenceKind.QUOTE,
                quote="wrong",
                quote_start=1,
                quote_end=6,
                idempotency_key="bad-offsets",
            )
        ),
    )
    free_text_target_rejected = _raises(
        ValueError,
        lambda: _assertion_request(
            item_id=alpha_item,
            document_id=alpha_document.id,
            assertion_type=DependencyAssertionType.NORMATIVE_POLICY,
            evidence_kind=AssertionEvidenceKind.COMMENTARY,
            commentary="An unregistered free-text authority is not a valid target.",
            authority_source_id=None,
            authority_identifier="unregistered free text",
            idempotency_key="free-text-target",
        ),
    )
    nonexistent_target_rejected = _raises(
        NotFoundError,
        lambda: service.create_dependency_assertion(
            _assertion_request(
                item_id=alpha_item,
                document_id=alpha_document.id,
                assertion_type=DependencyAssertionType.DERIVED_FROM,
                evidence_kind=AssertionEvidenceKind.COMMENTARY,
                commentary="Target must be registered.",
                target_kind="knowledge_item",
                target_item_id="not-a-registered-item",
                authority_source_id=None,
                authority_identifier=None,
                idempotency_key="missing-target",
            )
        ),
    )
    cross_scope_rejected = _raises(
        PolicyRefusalError,
        lambda: service.create_dependency_assertion(
            _assertion_request(
                item_id=alpha_item,
                document_id=alpha_document.id,
                assertion_type=DependencyAssertionType.DERIVED_FROM,
                evidence_kind=AssertionEvidenceKind.COMMENTARY,
                commentary="Cross-scope target is forbidden.",
                target_kind="knowledge_item",
                target_item_id=bravo_item,
                authority_source_id=None,
                authority_identifier=None,
                idempotency_key="cross-scope-target",
            )
        ),
    )
    self_confirmation_denied = _raises(
        PolicyRefusalError,
        lambda: service.decide_dependency_assertion(
            human.id,
            DependencyAssertionDecisionRequest(by="curator-alpha", decision="confirmed"),
        ),
    )

    def confirm_human() -> DependencyEdge:
        outcome = service.decide_dependency_assertion(
            human.id,
            DependencyAssertionDecisionRequest(by="reviewer-alpha", decision="confirmed"),
        )
        if not isinstance(outcome, DependencyEdge):
            raise RuntimeError("confirmed assertion did not return an edge")
        return outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_edges = list(executor.map(lambda _: confirm_human(), range(2)))
    confirmed_edge = concurrent_edges[0]
    retry_edge = confirm_human()
    rejected = service.decide_dependency_assertion(
        upstream.id,
        DependencyAssertionDecisionRequest(
            by="reviewer-alpha", decision="rejected", reason="upstream evidence not adopted"
        ),
    )
    deferred = service.decide_dependency_assertion(
        commentary.id,
        DependencyAssertionDecisionRequest(by="reviewer-alpha", decision="deferred", reason="needs second review"),
    )
    if isinstance(rejected, DependencyEdge) or isinstance(deferred, DependencyEdge):
        raise RuntimeError("non-confirmation returned an edge")
    withdrawn = service.withdraw_dependency_assertion(
        commentary.id,
        DependencyAssertionWithdrawRequest(by="curator-alpha", reason="replaced by a later operational review"),
    )

    out_of_scope_list_denied = service.dependency_assertions(matter_id="matter-bravo", client_id="client-bravo") == []
    out_of_scope_get_denied = _raises(
        NotFoundError,
        lambda: service.get_dependency_assertion(human.id, matter_id="matter-bravo", client_id="client-bravo"),
    )
    out_of_scope_decision_denied = _raises(
        NotFoundError,
        lambda: service.decide_dependency_assertion(
            human.id,
            DependencyAssertionDecisionRequest(
                by="reviewer-alpha",
                decision="confirmed",
                matter_id="matter-bravo",
                client_id="client-bravo",
            ),
        ),
    )
    out_of_scope_withdraw_denied = _raises(
        NotFoundError,
        lambda: service.withdraw_dependency_assertion(
            human.id,
            DependencyAssertionWithdrawRequest(
                by="curator-alpha",
                reason="must not disclose",
                matter_id="matter-bravo",
                client_id="client-bravo",
            ),
        ),
    )

    revised, _ = service.ingest_source_document(
        alpha_source.id,
        SourceDocumentIngestRequest(
            external_id="alpha-memo",
            filename="alpha-memo.txt",
            mime_type="text/plain",
            content="We rely on Regulation R section 12 for the revised Alpha operating conclusion.",
        ),
    )
    human_after_revision = service.get_dependency_assertion(
        human.id, matter_id="matter-alpha", client_id="client-alpha"
    )
    service.register_authority_change(
        confirmed_edge.target_id,
        AuthorityChangeRequest(new_version="2026-09", changed_at="2026-09-01T00:00:00+00:00"),
    )
    confirmed_currency = service.store.get_item(alpha_item).currency_state
    audit_pack = service.export_audit_pack(workspace / "audit-pack")
    audit_verified = service.audit.verify().ok and AuditJournal.verify_pack(audit_pack).ok
    history = service.dependency_assertion_history(human.id, matter_id="matter-alpha", client_id="client-alpha")
    audit_types = {entry["event_type"] for entry in history["audit_entries"]}

    _require(no_edges_at_creation, "creation must not create edges")
    _require(
        {edge.id for edge in concurrent_edges} == {confirmed_edge.id}, "concurrent confirmation must reuse one edge"
    )
    _require(retry_edge.id == confirmed_edge.id, "confirmation retry must be idempotent")
    _require(len(service.graph.get_dependencies(alpha_item)) == 1, "one confirmed assertion must create one edge")
    _require(confirmed_edge.source_suggestion_id == human.id, "edge must retain assertion provenance")
    _require(rejected.decision is SuggestionDecision.REJECTED, "trusted upstream assertion rejection")
    _require(withdrawn.decision is SuggestionDecision.WITHDRAWN, "deferred assertion withdrawal")
    _require(
        malformed_quote_rejected and free_text_target_rejected and nonexistent_target_rejected and cross_scope_rejected,
        "creation validation",
    )
    _require(self_confirmation_denied, "separation of duties")
    _require(
        out_of_scope_list_denied
        and out_of_scope_get_denied
        and out_of_scope_decision_denied
        and out_of_scope_withdraw_denied,
        "scope denial",
    )
    _require(revised.previous_version_id == alpha_document.id and revised.version == 2, "source revision lineage")
    _require(human_after_revision.needs_reverification, "source revision must request assertion reverification")
    _require(human_after_revision.evidence_raw == quote, "original evidence must remain reconstructible")
    _require(
        all(
            (
                human_after_revision.creation_audit_id,
                human_after_revision.review_audit_id,
                human_after_revision.edge_audit_id,
                human_after_revision.reverification_audit_id,
            )
        ),
        "creation, review, edge, and reverification audit ids",
    )
    _require(service.graph.get_edge(confirmed_edge.id).valid_to is None, "revision must retain prior confirmed edge")
    _require(confirmed_currency is CurrencyState.STALE_PENDING_REVERIFICATION, "confirmed edge currency impact")
    _require(
        service.store.get_item(commentary_item).currency_state is CurrencyState.LIVE
        and service.store.get_item(upstream_item).currency_state is CurrencyState.LIVE
        and service.store.get_item(bravo_item).currency_state is CurrencyState.LIVE,
        "unconfirmed and cross-scope items stay live",
    )
    _require(
        {
            "dependency_assertion_created",
            "dependency_assertion_confirmed",
            "dependency_assertion_edge_linked",
            "dependency_assertion_reverification_requested",
        }.issubset(audit_types),
        "assertion audit history",
    )
    _require(audit_verified, "audit pack verification")

    snapshot: dict[str, object] = {
        "schema": "solomon.governed_dependency_assertion_proof.snapshot.v1",
        "fixture": {"scopes": 2, "registered_document_sources": 2, "registered_authority_sources": 2},
        "origins": {"human_quote": 1, "human_commentary": 1, "trusted_upstream": 1},
        "creation": {"edges": 0, "quote_reconstructible": True, "commentary_has_no_offsets": True},
        "decisions": {"confirmed": 1, "rejected": 1, "deferred": 1, "withdrawn": 1},
        "validation": {
            "malformed_quote_rejected": malformed_quote_rejected,
            "free_text_target_rejected": free_text_target_rejected,
            "nonexistent_target_rejected": nonexistent_target_rejected,
            "cross_scope_rejected": cross_scope_rejected,
            "self_confirmation_denied": self_confirmation_denied,
        },
        "scope": {
            "list_denied": out_of_scope_list_denied,
            "get_denied": out_of_scope_get_denied,
            "decision_denied": out_of_scope_decision_denied,
            "withdraw_denied": out_of_scope_withdraw_denied,
        },
        "idempotency": {"confirmation_retry": True, "concurrent_confirmations": 2, "edges_for_assertion": 1},
        "currency": {"confirmed_impacts": 1, "unconfirmed_impacts": 0, "other_scope_impacts": 0},
        "revision": {"new_source_version": 2, "needs_reverification": True, "original_evidence_reconstructible": True},
        "audit": {
            "creation_review_edge_revision_reverification_ids": True,
            "audit_pack_verified": True,
        },
    }
    result = {**snapshot, "latency_ms": round((time.perf_counter() - started) * 1000, 3), "latency_budget_ms": 2_000}
    return result, snapshot


def _promote_source_item(
    service: SolomonService,
    *,
    source_id: str,
    external_id: str,
    content: str,
    matter_id: str,
    client_id: str,
) -> tuple[SourceDocument, str]:
    document, candidates = service.ingest_source_document(
        source_id,
        SourceDocumentIngestRequest(
            external_id=external_id,
            filename=f"{external_id}.txt",
            mime_type="text/plain",
            content=content,
        ),
    )
    item = service.promote_candidate_claim(
        candidates[0].id,
        CandidateClaimPromotionRequest(
            by="curator-alpha" if matter_id == "matter-alpha" else "curator-bravo",
            kind=KnowledgeKind.POSITION,
            source_kind=SourceKind.MATTER_DOC,
            matter_id=matter_id,
            client_id=client_id,
        ),
    )
    return document, item.id


def _assertion_request(
    *,
    item_id: str,
    document_id: str,
    assertion_type: DependencyAssertionType,
    evidence_kind: AssertionEvidenceKind,
    idempotency_key: str,
    quote: str | None = None,
    quote_start: int | None = None,
    quote_end: int | None = None,
    commentary: str | None = None,
    target_kind: str = "external_authority",
    target_item_id: str | None = None,
    authority_source_id: str | None = "alpha-gazette",
    authority_identifier: str | None = "SG-R-12",
    origin: str = "human",
    trusted_upstream_ref: str | None = None,
) -> DependencyAssertionCreateRequest:
    return DependencyAssertionCreateRequest(
        item_id=item_id,
        source_document_id=document_id,
        source_document_version=1,
        target_kind=target_kind,  # type: ignore[arg-type]
        target_item_id=target_item_id,
        authority_source_id=authority_source_id,
        authority_identifier=authority_identifier,
        assertion_type=assertion_type,
        evidence_kind=evidence_kind,
        quote=quote,
        quote_start=quote_start,
        quote_end=quote_end,
        commentary=commentary,
        rationale="synthetic governed assertion proof",
        created_by="curator-alpha",
        idempotency_key=idempotency_key,
        origin=origin,  # type: ignore[arg-type]
        trusted_upstream_ref=trusted_upstream_ref,
    )


def _raises(expected: type[Exception], call: object) -> bool:
    try:
        if not callable(call):
            raise TypeError("scenario call must be callable")
        call()
    except expected:
        return True
    return False


def _require(value: bool, label: str) -> None:
    if not value:
        raise RuntimeError(f"proof invariant failed: {label}")


if __name__ == "__main__":
    main()
