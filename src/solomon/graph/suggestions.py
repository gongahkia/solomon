# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from enum import Enum

from solomon.api.schemas import SolomonModel
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType

AUTHORITY_RE = re.compile(r"\b(Regulation\s+[A-Z]\s+(?:section|§)\s*\d+[A-Za-z0-9-]*)\b", re.IGNORECASE)


class SuggestionDecision(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class DependencySuggestion(SolomonModel):
    item_id: str
    authority_ref: str
    suggested_edge: DependencyEdge
    decision: SuggestionDecision = SuggestionDecision.PENDING


def suggest_authority_dependencies(
    *,
    item_id: str,
    content: str,
    boundary: KaypohBoundary,
    matter_id: str | None = None,
) -> list[DependencySuggestion]:
    sanitized = boundary.sanitize_context(content, matter_id=matter_id)
    suggestions: list[DependencySuggestion] = []
    for match in AUTHORITY_RE.finditer(sanitized.sanitized_text):
        authority_ref = " ".join(match.group(1).split())
        authority_id = authority_ref.lower().replace(" ", "-").replace("§", "section")
        suggestions.append(
            DependencySuggestion(
                item_id=item_id,
                authority_ref=authority_ref,
                suggested_edge=DependencyEdge(
                    source_id=item_id,
                    target_id=authority_id,
                    edge_type=EdgeType.INTERNAL_DEPENDS_ON_EXTERNAL,
                    target_kind="external_authority",
                    confidence=EdgeConfidence.LLM_SUGGESTED,
                    reason="candidate authority reference extracted from Kaypoh-sanitized text",
                ),
            )
        )
    return suggestions


def confirm_suggestion(suggestion: DependencySuggestion, *, by: str) -> DependencyEdge:
    return suggestion.suggested_edge.model_copy(
        update={
            "confidence": EdgeConfidence.HUMAN_CONFIRMED,
            "created_by": by,
            "reason": f"human confirmed suggestion: {suggestion.authority_ref}",
        }
    )


def reject_suggestion(suggestion: DependencySuggestion, *, by: str) -> DependencySuggestion:
    return suggestion.model_copy(
        update={
            "decision": SuggestionDecision.REJECTED,
            "suggested_edge": suggestion.suggested_edge.model_copy(
                update={"created_by": by, "reason": f"human rejected suggestion: {suggestion.authority_ref}"}
            ),
        }
    )

