# SPDX-License-Identifier: Apache-2.0
"""Local Kaypoh-derived review and tokenization engine vendored into Solomon."""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Iterable

from solomon.boundary.engine.jurisdictions import resolve_pack
from solomon.boundary.engine.schemas import MappingEntry, ReviewFinding

CLIENT_RE = re.compile(r"\bClient\s+[A-Z][A-Za-z0-9&.-]*\b")
ORG_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4}\s+"
    r"(?:Pte\s+Ltd|LLC|Ltd|Limited|Inc|Corp|Corporation)\b"
)
PERSON_RE = re.compile(r"\b(?:Jane|John|Alice|Bob|Mary|Michael|Sarah|David)\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d -]{7,}\d)\b")
NATIONAL_ID_RE = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
HIGH_RISK_RE = re.compile(
    r"\b(?:MNPI|material\s+non[- ]public|inside\s+information|earnings\s+before\s+release|"
    r"non[- ]public\s+results|SSN|passport\s+number|credit\s+card)\b",
    re.IGNORECASE,
)


def review_text(
    text: str,
    *,
    source_jurisdiction: str,
    destination_jurisdiction: str,
) -> tuple[str, list[ReviewFinding]]:
    findings: list[ReviewFinding] = []
    source_pack = resolve_pack(source_jurisdiction)
    destination_pack = resolve_pack(destination_jurisdiction)
    for pattern, kind, severity in [
        (CLIENT_RE, "client_reference", "medium"),
        (ORG_RE, "organization", "medium"),
        (PERSON_RE, "person", "medium"),
        (EMAIL_RE, "email", "medium"),
        (PHONE_RE, "phone", "medium"),
        (NATIONAL_ID_RE, "national_id", "high"),
        (HIGH_RISK_RE, "mnpi_or_high_risk_secret", "high"),
    ]:
        findings.extend(_find(pattern, text, kind=kind, severity=severity, jurisdiction=source_pack.code))

    strict_terms = set(source_pack.strict_terms) | set(destination_pack.strict_terms)
    for term in strict_terms:
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            findings.append(
                ReviewFinding(
                    kind="jurisdiction_strict_term",
                    text=match.group(0),
                    severity="high" if "inside information" in term.lower() else "medium",
                    start=match.start(),
                    end=match.end(),
                    jurisdiction=destination_pack.code,
                )
            )

    classification = "HIGH_RISK" if any(finding.severity == "high" for finding in findings) else "SAFE"
    return classification, _dedupe_findings(findings)


def pseudonymize_text(text: str) -> tuple[str, list[MappingEntry]]:
    replacements = _collect_replacements(text)
    output = text
    mapping: list[MappingEntry] = []
    counters: dict[str, int] = {}
    offset = 0
    for start, end, entity_type, original in replacements:
        counters[entity_type] = counters.get(entity_type, 0) + 1
        placeholder = f"[{entity_type}_{counters[entity_type]}]"
        adjusted_start = start + offset
        adjusted_end = end + offset
        output = output[:adjusted_start] + placeholder + output[adjusted_end:]
        offset += len(placeholder) - (end - start)
        mapping.append(MappingEntry(placeholder=placeholder, original_text=original, entity_type=entity_type))
    return output, mapping


def reidentify_text(text: str, mapping: Iterable[MappingEntry]) -> tuple[str, int]:
    output = text
    replacements = 0
    for entry in mapping:
        if entry.placeholder in output:
            output = output.replace(entry.placeholder, entry.original_text)
            replacements += 1
    return output, replacements


def document_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def scrub_document_base64(document_base64: str) -> dict[str, object]:
    decoded = base64.b64decode(document_base64.encode("ascii"), validate=True)
    return {
        "document_base64": base64.b64encode(decoded).decode("ascii"),
        "metadata_findings": [],
        "sha256": hashlib.sha256(decoded).hexdigest(),
    }


def _find(
    pattern: re.Pattern[str],
    text: str,
    *,
    kind: str,
    severity: str,
    jurisdiction: str,
) -> list[ReviewFinding]:
    return [
        ReviewFinding(
            kind=kind,
            text=match.group(0),
            severity=severity,
            start=match.start(),
            end=match.end(),
            jurisdiction=jurisdiction,
        )
        for match in pattern.finditer(text)
    ]


def _dedupe_findings(findings: list[ReviewFinding]) -> list[ReviewFinding]:
    seen: set[tuple[str, str, int | None, int | None]] = set()
    deduped: list[ReviewFinding] = []
    for finding in findings:
        key = (finding.kind, finding.text.lower(), finding.start, finding.end)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _collect_replacements(text: str) -> list[tuple[int, int, str, str]]:
    candidates: list[tuple[int, int, str, str]] = []
    for pattern, entity_type in [
        (EMAIL_RE, "EMAIL"),
        (NATIONAL_ID_RE, "NATIONAL_ID"),
        (CLIENT_RE, "CLIENT"),
        (ORG_RE, "ORG"),
        (PERSON_RE, "PERSON"),
        (PHONE_RE, "PHONE"),
    ]:
        candidates.extend((match.start(), match.end(), entity_type, match.group(0)) for match in pattern.finditer(text))
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    occupied_until = -1
    for candidate in candidates:
        start, end, _entity_type, _original = candidate
        if start < occupied_until:
            continue
        selected.append(candidate)
        occupied_until = end
    return selected
