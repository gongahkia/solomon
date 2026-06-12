# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from solomon.api.service import DependencyRequest, SolomonService
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.suggestions import (
    confirm_suggestion,
    extract_defined_terms_and_citations,
    reject_suggestion,
    suggest_authority_dependencies,
    suggest_authority_dependencies_with_llm,
)
from solomon.orchestrator.models import EndpointKind, ModelRequest, ModelResponse, ModelRouter


class SuggestionKaypohClient:
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


def test_suggest_confirm_and_reject_dependencies() -> None:
    boundary = KaypohBoundary(SuggestionKaypohClient())

    suggestions = suggest_authority_dependencies(
        item_id="item-1",
        content="This relies on Regulation R section 12.",
        boundary=boundary,
    )
    confirmed = confirm_suggestion(suggestions[0], by="Partner A")
    rejected = reject_suggestion(suggestions[0], by="Partner A")

    assert suggestions[0].suggested_edge.confidence is EdgeConfidence.LLM_SUGGESTED
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
        boundary=KaypohBoundary(),
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
    boundary = KaypohBoundary(SuggestionKaypohClient())

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
