# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Literal

from solomon.api.schemas import SolomonModel
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType
from solomon.orchestrator.models import ModelRequest, ModelRouter

AUTHORITY_RE = re.compile(r"\b(Regulation\s+[A-Z]\s+(?:section|§)\s*\d+[A-Za-z0-9-]*)\b", re.IGNORECASE)
DEFINED_TERM_QUOTED_RE = re.compile(
    r'"(?P<term>[A-Z][A-Za-z0-9 &/-]{1,80})"\s+(?:means|shall mean|has the meaning)\s+(?P<definition>[^.;]+)',
    re.IGNORECASE,
)
DEFINED_TERM_PAREN_RE = re.compile(
    r"\b(?P<definition>[A-Z][A-Za-z0-9 &/-]{2,120}?)\s*\(\s*\"(?P<term>[A-Z][A-Za-z0-9 &/-]{1,80})\"\s*\)"
)
CASE_CITATION_RE = re.compile(
    r"\b(?P<citation>[A-Z][A-Za-z.&' -]{2,80}\s+v\.?\s+[A-Z][A-Za-z.&' -]{2,80}"
    r"(?:\s+\[[0-9]{4}\]\s+[A-Z0-9 .-]+\s+[0-9]+)?)"
)
SECTION_CITATION_RE = re.compile(
    r"\b(?P<citation>[A-Z][A-Za-z0-9 &/-]{2,80}\s+(?:Act|Code|Regulation|Rules?)"
    r"(?:\s+[0-9]{4})?\s+(?:section|s\.|§)\s*[0-9A-Za-z-]+)",
    re.IGNORECASE,
)


class SuggestionDecision(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class DependencySuggestion(SolomonModel):
    item_id: str
    authority_ref: str
    suggested_edge: DependencyEdge
    decision: SuggestionDecision = SuggestionDecision.PENDING


class DefinedTerm(SolomonModel):
    term: str
    definition: str
    source: Literal["quoted-definition", "parenthetical-definition"]


class CitationReference(SolomonModel):
    text: str
    kind: Literal["authority", "case", "section"]
    normalized_id: str


class ReferenceExtraction(SolomonModel):
    defined_terms: list[DefinedTerm]
    citations: list[CitationReference]
    sanitized: bool = False


def extract_defined_terms_and_citations(
    *,
    content: str,
    boundary: KaypohBoundary | None = None,
    matter_id: str | None = None,
) -> ReferenceExtraction:
    """Extract review hints from Kaypoh-sanitized legal text.

    This is deliberately deterministic and conservative. It creates candidate
    references for a human dependency capture workflow; it does not assert that
    every citation is legally load-bearing.
    """

    sanitized = False
    text = content
    if boundary is not None:
        sanitized_context = boundary.sanitize_context(content, matter_id=matter_id)
        text = sanitized_context.sanitized_text
        sanitized = True

    terms: dict[str, DefinedTerm] = {}
    for match in DEFINED_TERM_QUOTED_RE.finditer(text):
        term = _clean(match.group("term"))
        terms.setdefault(
            term.lower(),
            DefinedTerm(
                term=term,
                definition=_clean(match.group("definition")),
                source="quoted-definition",
            ),
        )
    for match in DEFINED_TERM_PAREN_RE.finditer(text):
        term = _clean(match.group("term"))
        terms.setdefault(
            term.lower(),
            DefinedTerm(
                term=term,
                definition=_clean(match.group("definition")),
                source="parenthetical-definition",
            ),
        )

    citations: dict[str, CitationReference] = {}
    for match in AUTHORITY_RE.finditer(text):
        citation = _clean(match.group(1))
        citations.setdefault(
            f"authority:{citation.lower()}",
            CitationReference(text=citation, kind="authority", normalized_id=_authority_id(citation)),
        )
    for match in CASE_CITATION_RE.finditer(text):
        citation = _clean(match.group("citation"))
        citations.setdefault(
            f"case:{citation.lower()}",
            CitationReference(text=citation, kind="case", normalized_id=_citation_id(citation)),
        )
    for match in SECTION_CITATION_RE.finditer(text):
        citation = _clean(match.group("citation"))
        citations.setdefault(
            f"section:{citation.lower()}",
            CitationReference(text=citation, kind="section", normalized_id=_citation_id(citation)),
        )

    return ReferenceExtraction(
        defined_terms=sorted(terms.values(), key=lambda term: term.term.lower()),
        citations=sorted(citations.values(), key=lambda citation: (citation.kind, citation.normalized_id)),
        sanitized=sanitized,
    )


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


def suggest_authority_dependencies_with_llm(
    *,
    item_id: str,
    content: str,
    boundary: KaypohBoundary,
    router: ModelRouter,
    matter_id: str | None = None,
) -> list[DependencySuggestion]:
    sanitized = boundary.sanitize_context(content, matter_id=matter_id)
    prompt = "\n".join(
        [
            "Extract load-bearing external legal authorities from this sanitized text.",
            "Return strict JSON only in this shape:",
            '{"dependencies":[{"authority_ref":"...","authority_id":"...","reason":"..."}]}',
            "Do not include client names or confidential facts.",
            sanitized.sanitized_text,
        ]
    )
    routed = router.complete(ModelRequest(prompt=prompt, matter_id=matter_id))
    payload = _parse_llm_dependency_payload(routed.response.text)
    suggestions: list[DependencySuggestion] = []
    for dependency in payload:
        authority_ref = _clean(str(dependency["authority_ref"]))
        authority_id = _citation_id(str(dependency["authority_id"]))
        reason = _clean(str(dependency.get("reason") or "LLM-assisted authority extraction"))
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
                    reason=f"LLM-assisted candidate from Kaypoh-sanitized text: {reason}",
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


def _clean(value: str) -> str:
    return " ".join(value.strip().split())


def _authority_id(value: str) -> str:
    return _citation_id(value).replace("section", "section")


def _citation_id(value: str) -> str:
    normalized = value.lower().replace("§", " section ")
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _parse_llm_dependency_payload(text: str) -> list[dict[str, object]]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM dependency response must be a JSON object")
    raw_dependencies = parsed.get("dependencies")
    if not isinstance(raw_dependencies, list):
        raise ValueError("LLM dependency response must contain a dependencies list")
    dependencies: list[dict[str, object]] = []
    for raw in raw_dependencies:
        if not isinstance(raw, dict):
            raise ValueError("LLM dependency entries must be JSON objects")
        if not isinstance(raw.get("authority_ref"), str) or not isinstance(raw.get("authority_id"), str):
            raise ValueError("LLM dependency entries require authority_ref and authority_id strings")
        dependencies.append(raw)
    return dependencies
