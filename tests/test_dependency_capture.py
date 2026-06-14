# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from solomon.api.service import (
    DependencyRequest,
    DependencySuggestionDecisionRequest,
    DependencySuggestionRequest,
    IngestRequest,
    SolomonService,
)
from solomon.boundary.solomon import SolomonBoundary
from solomon.currency.models import KnowledgeKind, SourceKind
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.suggestions import (
    SuggestionDecision,
    confirm_suggestion,
    extract_defined_terms_and_citations,
    reject_suggestion,
    suggest_authority_dependencies,
    suggest_authority_dependencies_with_llm,
)
from solomon.orchestrator.models import EndpointKind, ModelRequest, ModelResponse, ModelRouter


class SuggestionBoundaryClient:
    def pseudonymize(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {
            "pseudonymized_text": kwargs["request"]["text"],
            "mapping": [],
            "document_hash": "d" * 64,
        }

    def review(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"classification": "SAFE", "findings": []}

    def reidentify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"reidentified_text": kwargs["anonymized_text"], "replacement_count": 0}

    def scrub_document(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"document_base64": kwargs["document_base64"]}


def test_manual_dependency_tagging_service_api(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    edge = service.add_dependency(
        DependencyRequest(
            source_id="item-1",
            target_id="reg-r-12",
            edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
            target_kind="external_authority",
            created_by="associate",
        )
    )

    assert edge.confidence is EdgeConfidence.HUMAN_ASSERTED
    assert service.graph.get_dependencies("item-1")[0].target_id == "reg-r-12"


def test_ingest_creates_pending_dependency_suggestions_and_dedupes_reruns(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")

    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="This position relies on Regulation R section 12.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-deps",
        )
    )

    suggestions = service.dependency_suggestions(item_id=item.id)
    rerun = service.suggest_dependencies(DependencySuggestionRequest(item_id=item.id))

    assert len(suggestions) == 1
    assert suggestions[0].decision is SuggestionDecision.PENDING
    assert suggestions[0].suggested_edge.target_id == "regulation-r-section-12"
    assert suggestions[0].source == "deterministic"
    assert rerun == []


def test_confirm_and_reject_dependency_suggestions_update_queue_and_edges(tmp_path: Path) -> None:
    service = SolomonService(data_dir=tmp_path / "data", journal_dir=tmp_path / "journal")
    item = service.ingest(
        IngestRequest(
            kind=KnowledgeKind.POSITION,
            content="Regulation R section 12 controls. Regulation S section 9 also matters.",
            source_kind=SourceKind.PARTNER,
            source_ref="memo-deps",
        )
    )
    suggestions = service.dependency_suggestions(item_id=item.id, limit=10)

    confirmed_edge = service.confirm_dependency_suggestion(
        suggestions[0].id,
        DependencySuggestionDecisionRequest(by="Partner A"),
    )
    rejected = service.reject_dependency_suggestion(
        suggestions[1].id,
        DependencySuggestionDecisionRequest(by="Partner A"),
    )

    decisions = {suggestion.id: suggestion.decision for suggestion in service.dependency_suggestions(item_id=item.id)}
    assert confirmed_edge.confidence is EdgeConfidence.HUMAN_CONFIRMED
    assert service.graph.get_dependencies(item.id) == [confirmed_edge]
    assert rejected.decision is SuggestionDecision.REJECTED
    assert decisions[suggestions[0].id] is SuggestionDecision.CONFIRMED
    assert decisions[suggestions[1].id] is SuggestionDecision.REJECTED
    raw_journal = (tmp_path / "journal" / "journal.jsonl").read_text(encoding="utf-8")
    assert "dependency_suggestion_created" in raw_journal
    assert "dependency_suggestion_confirmed" in raw_journal
    assert "dependency_suggestion_rejected" in raw_journal
    assert "Regulation R section 12 controls" not in raw_journal


def test_suggest_confirm_and_reject_dependencies() -> None:
    boundary = SolomonBoundary(SuggestionBoundaryClient())

    suggestions = suggest_authority_dependencies(
        item_id="item-1",
        content="This relies on Regulation R section 12.",
        boundary=boundary,
    )
    confirmed = confirm_suggestion(suggestions[0], by="Partner A")
    rejected = reject_suggestion(suggestions[0], by="Partner A")

    assert suggestions[0].suggested_edge.confidence is EdgeConfidence.LLM_SUGGESTED
    assert suggestions[0].suggested_edge.target_id == "regulation-r-section-12"
    assert confirmed.confidence is EdgeConfidence.HUMAN_CONFIRMED
    assert rejected.decision.value == "rejected"


def test_llm_dependency_capture_uses_boundary_sanitized_prompt() -> None:
    class CapturingEndpoint:
        kind = EndpointKind.REMOTE_ZDR

        def __init__(self) -> None:
            self.seen_prompt = ""

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.seen_prompt = request.prompt
            return ModelResponse(
                text=(
                    '{"dependencies":[{"authority_ref":"Regulation R section 12",'
                    '"authority_id":"regulation-r-section-12","reason":"explicit citation"}]}'
                ),
                endpoint=self.kind,
            )

    remote = CapturingEndpoint()
    local = CapturingEndpoint()
    suggestions = suggest_authority_dependencies_with_llm(
        item_id="item-1",
        content="Client A relies on Regulation R section 12 for structure X.",
        boundary=SolomonBoundary(),
        router=ModelRouter(remote=remote, local=local),
        matter_id="matter-a",
    )

    assert "Client A" not in remote.seen_prompt
    assert "[CLIENT_1]" in remote.seen_prompt
    assert suggestions[0].authority_ref == "Regulation R section 12"
    assert suggestions[0].suggested_edge.target_id == "regulation-r-section-12"
    assert suggestions[0].suggested_edge.confidence is EdgeConfidence.LLM_SUGGESTED
    assert "LLM-assisted candidate" in str(suggestions[0].suggested_edge.reason)


def test_extract_defined_terms_and_citations_after_boundary_sanitization() -> None:
    boundary = SolomonBoundary(SuggestionBoundaryClient())

    extraction = extract_defined_terms_and_citations(
        content=(
            '"Restricted Person" means any adviser in the group. '
            "The memo relies on Regulation R section 12 and Alpha Pte Ltd v. Beta LLC [2024] SGHC 12."
        ),
        boundary=boundary,
    )

    assert extraction.sanitized is True
    assert extraction.defined_terms[0].term == "Restricted Person"
    assert {citation.kind for citation in extraction.citations} == {"authority", "case"}
    assert "regulation-r-section-12" in {citation.normalized_id for citation in extraction.citations}


def test_reference_parser_uses_eyecite_for_full_case_and_law_citations() -> None:
    extraction = extract_defined_terms_and_citations(
        content=(
            "The brief cites Bush v. Gore, 531 U.S. 98, 99-100 (2000), "
            "then Mass. Gen. Laws ch. 1, § 2."
        )
    )

    citations = {citation.normalized_id: citation for citation in extraction.citations}

    case = citations["bush-v-gore-531-u-s-98-99-100-scotus-2000"]
    law = citations["mass-gen-laws-ch-1-section-2"]
    assert case.kind == "case"
    assert case.parser == "eyecite"
    assert case.metadata["metadata"]["pin_cite"] == "99-100"
    assert law.kind == "section"
    assert law.parser == "eyecite"
    assert law.metadata["groups"]["section"] == "2"


def test_reference_parser_handles_defined_terms_and_non_us_case_grammar() -> None:
    extraction = extract_defined_terms_and_citations(
        content=(
            "A regulated payment institution (\"Payment Institution\") must keep records. "
            "The analysis distinguishes Alpha Pte Ltd v. Beta LLC [2024] SGHC 12."
        )
    )

    assert extraction.defined_terms[0].term == "Payment Institution"
    assert extraction.defined_terms[0].definition == "A regulated payment institution"
    assert extraction.defined_terms[0].source == "parenthetical-definition"
    case = next(citation for citation in extraction.citations if citation.kind == "case")
    assert case.parser == "solomon-grammar"
    assert case.text == "Alpha Pte Ltd v. Beta LLC [2024] SGHC 12"


def test_reference_parser_ignores_bare_v_token() -> None:
    extraction = extract_defined_terms_and_citations(content="FuzzContent::V")

    assert extraction.citations == []
