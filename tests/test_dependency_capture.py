# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

from solomon.api.service import DependencyRequest, SolomonService
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.graph.models import EdgeConfidence, EdgeType
from solomon.graph.suggestions import confirm_suggestion, reject_suggestion, suggest_authority_dependencies


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

