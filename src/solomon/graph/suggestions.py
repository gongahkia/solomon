# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from solomon.api.schemas import SolomonModel
from solomon.boundary.kaypoh import KaypohBoundary
from solomon.currency.models import new_uuid7, now_utc
from solomon.graph.models import DependencyEdge, EdgeConfidence, EdgeType
from solomon.orchestrator.models import ModelRequest, ModelRouter

TOKEN_RE = re.compile(r"\[[0-9]{4}\]|[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|§|s\.|v\.?|[.,;:()\"]")
AUTHORITY_NOUNS = {"act", "code", "regulation", "regulations", "rule", "rules"}
SECTION_MARKERS = {"section", "s.", "§"}
CASE_CONNECTORS = {"of", "the", "and", "&", "pte", "ltd", "llc", "inc", "corp", "co"}
QUOTE_DEFINITION_MARKERS = ("shall mean", "has the meaning", "means")


class SuggestionDecision(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class DependencySuggestion(SolomonModel):
    id: str = Field(default_factory=new_uuid7)
    item_id: str
    authority_ref: str
    suggested_edge: DependencyEdge
    decision: SuggestionDecision = SuggestionDecision.PENDING
    source: Literal["deterministic", "llm"] = "deterministic"
    created_at: datetime = Field(default_factory=now_utc)
    decided_at: datetime | None = None
    decided_by: str | None = None


class DefinedTerm(SolomonModel):
    term: str
    definition: str
    source: Literal["quoted-definition", "parenthetical-definition"]
    span_start: int | None = None
    span_end: int | None = None


class CitationReference(SolomonModel):
    text: str
    kind: Literal["authority", "case", "section"]
    normalized_id: str
    parser: Literal["eyecite", "solomon-grammar"] = "solomon-grammar"
    span_start: int | None = None
    span_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    """Extract review hints from Kaypoh-sanitized legal text."""

    sanitized = False
    text = content
    if boundary is not None:
        sanitized_context = boundary.sanitize_context(content, matter_id=matter_id)
        text = sanitized_context.sanitized_text
        sanitized = True

    terms = _extract_defined_terms(text)
    citations = _extract_citations(text)

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
    references = extract_defined_terms_and_citations(content=sanitized.sanitized_text)
    for citation in references.citations:
        if citation.kind not in {"authority", "section"}:
            continue
        authority_ref = citation.text
        authority_id = citation.normalized_id
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
                source="deterministic",
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
                source="llm",
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
            "decided_by": by,
            "decided_at": now_utc(),
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


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int

    @property
    def lower(self) -> str:
        return self.text.lower()


def _extract_defined_terms(text: str) -> dict[str, DefinedTerm]:
    terms: dict[str, DefinedTerm] = {}
    for term in _scan_quoted_defined_terms(text):
        terms.setdefault(term.term.lower(), term)
    for term in _scan_parenthetical_defined_terms(text):
        terms.setdefault(term.term.lower(), term)
    return terms


def _scan_quoted_defined_terms(text: str) -> list[DefinedTerm]:
    terms: list[DefinedTerm] = []
    position = 0
    while True:
        opening = text.find('"', position)
        if opening == -1:
            return terms
        closing = text.find('"', opening + 1)
        if closing == -1:
            return terms
        raw_term = text[opening + 1 : closing]
        after = text[closing + 1 :]
        marker, marker_start = _definition_marker(after)
        if marker is not None and _looks_like_defined_term(raw_term):
            definition_start = closing + 1 + marker_start + len(marker)
            definition_end = _definition_end(text, definition_start)
            terms.append(
                DefinedTerm(
                    term=_clean(raw_term),
                    definition=_clean(text[definition_start:definition_end]),
                    source="quoted-definition",
                    span_start=opening,
                    span_end=definition_end,
                )
            )
        position = closing + 1


def _scan_parenthetical_defined_terms(text: str) -> list[DefinedTerm]:
    terms: list[DefinedTerm] = []
    position = 0
    while True:
        opening = text.find('("', position)
        if opening == -1:
            return terms
        term_start = opening + 2
        term_end = text.find('"', term_start)
        if term_end == -1 or term_end + 1 >= len(text) or text[term_end + 1] != ")":
            position = opening + 2
            continue
        raw_term = text[term_start:term_end]
        if _looks_like_defined_term(raw_term):
            definition_start = _definition_start_before(text, opening)
            definition = _clean(text[definition_start:opening])
            if definition:
                terms.append(
                    DefinedTerm(
                        term=_clean(raw_term),
                        definition=definition,
                        source="parenthetical-definition",
                        span_start=definition_start,
                        span_end=term_end + 2,
                    )
                )
        position = term_end + 2


def _extract_citations(text: str) -> dict[str, CitationReference]:
    citations: dict[str, CitationReference] = {}
    occupied_spans: list[tuple[int, int]] = []

    for citation in _eyecite_citations(text):
        key = f"{citation.kind}:{citation.normalized_id}"
        citations.setdefault(key, citation)
        if citation.span_start is not None and citation.span_end is not None:
            occupied_spans.append((citation.span_start, citation.span_end))

    for citation in _grammar_citations(text):
        if citation.span_start is not None and citation.span_end is not None:
            if _overlaps_any((citation.span_start, citation.span_end), occupied_spans):
                continue
        key = f"{citation.kind}:{citation.normalized_id}"
        citations.setdefault(key, citation)

    return citations


def _eyecite_citations(text: str) -> list[CitationReference]:
    eyecite = importlib.import_module("eyecite")
    citations: list[CitationReference] = []
    for citation in eyecite.get_citations(text):
        span_start, span_end = citation.span()
        rendered = _clean(_eyecite_rendered_text(citation, text[span_start:span_end]))
        if not rendered:
            continue
        kind = _eyecite_kind(type(citation).__name__)
        citations.append(
            CitationReference(
                text=rendered,
                kind=kind,
                normalized_id=_citation_id(rendered),
                parser="eyecite",
                span_start=span_start,
                span_end=span_end,
                metadata=_eyecite_metadata(citation),
            )
        )
    return citations


def _grammar_citations(text: str) -> list[CitationReference]:
    tokens = [Token(match.group(0), match.start(), match.end()) for match in TOKEN_RE.finditer(text)]
    citations: list[CitationReference] = []
    occupied_spans: list[tuple[int, int]] = []
    for candidate in [
        *_parse_regulation_references(tokens, text),
        *_parse_section_references(tokens, text),
        *_parse_case_references(tokens, text),
    ]:
        if candidate.span_start is not None and candidate.span_end is not None:
            span = (candidate.span_start, candidate.span_end)
            if _overlaps_any(span, occupied_spans):
                continue
            occupied_spans.append(span)
        citations.append(candidate)
    return citations


def _parse_regulation_references(tokens: list[Token], text: str) -> list[CitationReference]:
    citations: list[CitationReference] = []
    for index, token in enumerate(tokens):
        if token.lower not in {"regulation", "regulations", "rule", "rules"}:
            continue
        if index + 3 >= len(tokens):
            continue
        marker_index = index + 2
        if tokens[marker_index].lower not in SECTION_MARKERS:
            continue
        if not _is_section_number(tokens[marker_index + 1].text):
            continue
        start, end = tokens[index].start, tokens[marker_index + 1].end
        raw = _clean(text[start:end])
        citations.append(
            CitationReference(
                text=raw,
                kind="authority",
                normalized_id=_authority_id(raw),
                parser="solomon-grammar",
                span_start=start,
                span_end=end,
                metadata={"grammar": "authority-section"},
            )
        )
    return citations


def _parse_section_references(tokens: list[Token], text: str) -> list[CitationReference]:
    citations: list[CitationReference] = []
    for index, token in enumerate(tokens):
        if token.lower not in AUTHORITY_NOUNS:
            continue
        marker_index = _next_section_marker(tokens, index + 1)
        if marker_index is None or marker_index + 1 >= len(tokens):
            continue
        if not _is_section_number(tokens[marker_index + 1].text):
            continue
        start_index = _authority_title_start(tokens, index)
        start, end = tokens[start_index].start, tokens[marker_index + 1].end
        raw = _clean(text[start:end])
        citations.append(
            CitationReference(
                text=raw,
                kind="section",
                normalized_id=_citation_id(raw),
                parser="solomon-grammar",
                span_start=start,
                span_end=end,
                metadata={"grammar": "statute-section"},
            )
        )
    return citations


def _parse_case_references(tokens: list[Token], text: str) -> list[CitationReference]:
    citations: list[CitationReference] = []
    for index, token in enumerate(tokens):
        if token.lower.rstrip(".") != "v":
            continue
        start_index = _case_party_start(tokens, index)
        end_index = _case_party_end(tokens, index)
        if start_index >= index or end_index <= index:
            continue
        start, end = tokens[start_index].start, tokens[end_index].end
        raw = _trim_case_citation(_clean(text[start:end]))
        if raw:
            citations.append(
                CitationReference(
                    text=raw,
                    kind="case",
                    normalized_id=_citation_id(raw),
                    parser="solomon-grammar",
                    span_start=start,
                    span_end=start + len(raw),
                    metadata={"grammar": "case-name"},
                )
            )
    return citations


def _definition_marker(text: str) -> tuple[str | None, int]:
    stripped_start = len(text) - len(text.lstrip())
    lowered = text[stripped_start:].lower()
    for marker in QUOTE_DEFINITION_MARKERS:
        if lowered.startswith(marker):
            return marker, stripped_start
    return None, -1


def _definition_end(text: str, start: int) -> int:
    candidates = [idx for idx in (text.find(".", start), text.find(";", start)) if idx != -1]
    return min(candidates) if candidates else len(text)


def _definition_start_before(text: str, end: int) -> int:
    boundaries = [text.rfind(marker, 0, end) for marker in ".;\n"]
    return max(boundaries) + 1


def _looks_like_defined_term(value: str) -> bool:
    cleaned = _clean(value)
    return 1 < len(cleaned) <= 80 and cleaned[0].isupper()


def _eyecite_rendered_text(citation: Any, fallback: str) -> str:
    renderer = getattr(citation, "corrected_citation_full", None)
    if callable(renderer):
        rendered = renderer()
        if rendered:
            return str(rendered)
    return fallback


def _eyecite_kind(type_name: str) -> Literal["authority", "case", "section"]:
    if "CaseCitation" in type_name or type_name in {"IdCitation", "SupraCitation", "ReferenceCitation"}:
        return "case"
    if "LawCitation" in type_name:
        return "section"
    return "authority"


def _eyecite_metadata(citation: Any) -> dict[str, Any]:
    metadata = getattr(citation, "metadata", None)
    groups = getattr(citation, "groups", None)
    result: dict[str, Any] = {"type": type(citation).__name__}
    if isinstance(groups, dict):
        result["groups"] = groups
    if metadata is not None:
        result["metadata"] = {
            key: value
            for key, value in vars(metadata).items()
            if value is not None and isinstance(value, str | int | float | bool)
        }
    return result


def _next_section_marker(tokens: list[Token], start: int) -> int | None:
    for index in range(start, min(start + 6, len(tokens))):
        if tokens[index].lower in SECTION_MARKERS:
            return index
    return None


def _authority_title_start(tokens: list[Token], noun_index: int) -> int:
    start = noun_index
    while start > 0:
        previous = tokens[start - 1]
        if previous.text in {".", ";", ":", ")", "("}:
            break
        if previous.text == ",":
            break
        if not (previous.text[:1].isupper() or previous.text.isdigit() or previous.lower in CASE_CONNECTORS):
            break
        start -= 1
    return start


def _case_party_start(tokens: list[Token], v_index: int) -> int:
    start = v_index - 1
    while start > 0:
        previous = tokens[start - 1]
        if previous.text in {".", ";", ":", ")", "("}:
            break
        if previous.text == ",":
            break
        if not (previous.text[:1].isupper() or previous.lower in CASE_CONNECTORS):
            break
        start -= 1
    return start


def _case_party_end(tokens: list[Token], v_index: int) -> int:
    end = v_index + 1
    while end + 1 < len(tokens):
        current = tokens[end + 1]
        if current.text in {";", ":"}:
            break
        if current.text == "." and end + 2 >= len(tokens):
            break
        if current.lower == "and" and end + 2 < len(tokens) and tokens[end + 2].text[:1].isupper():
            break
        if current.text == "." and end + 2 < len(tokens) and tokens[end + 2].text[:1].isupper():
            break
        end += 1
        if current.text == ")" or current.text.startswith("["):
            continue
    return end


def _trim_case_citation(value: str) -> str:
    cleaned = value.strip(" ,.;")
    for separator in (" The ", " This ", " It "):
        index = cleaned.find(separator)
        if index != -1:
            cleaned = cleaned[:index]
    return cleaned.strip(" ,.;")


def _is_section_number(value: str) -> bool:
    return bool(value) and any(character.isdigit() for character in value)


def _overlaps_any(span: tuple[int, int], occupied_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_spans)


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
