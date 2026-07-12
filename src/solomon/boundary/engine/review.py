# SPDX-License-Identifier: Apache-2.0
"""Local Solomon boundary review and tokenization engine."""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import re
from collections.abc import Iterable

from solomon.boundary.engine.jurisdictions import resolve_pack
from solomon.boundary.engine.schemas import MappingEntry, OpaqueRedaction, PlaceholderReplacement, ReviewFinding

CLIENT_RE = re.compile(r"\bClient\s+[A-Z][A-Za-z0-9&.-]*\b")
ORG_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4}\s+"
    r"(?:Pte\s+Ltd|LLC|Ltd|Limited|Inc|Corp|Corporation)\b"
)
PERSON_RE = re.compile(r"\b(?:Dr\s+|Mr\s+|Ms\s+|Mrs\s+)?(?:Jane|John|Alice|Bob|Mary|Michael|Sarah|David|Tan)\b")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+?\d[\d -]{7,}\d)\b")
NATIONAL_ID_RE = re.compile(r"\b[STFGM]\d{7}[A-Z]\b", re.IGNORECASE)
PASSPORT_RE = re.compile(r"\b(?:passport(?:\s+number)?|passport no\.?)\s*[:#-]?\s*([A-Z0-9]{6,12})\b", re.IGNORECASE)
BANK_ACCOUNT_RE = re.compile(
    r"\b(?:bank\s+account|acct\.?|account\s+number)\s*[:#-]?\s*([0-9][0-9 -]{6,20}[0-9])\b",
    re.IGNORECASE,
)
CREDIT_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
DOB_RE = re.compile(
    r"\b(?:date\s+of\s+birth|dob|born)\s*[:#-]?\s*([0-3]?\d[/-][01]?\d[/-](?:19|20)\d{2})\b",
    re.IGNORECASE,
)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
IMEI_RE = re.compile(r"\b(?:IMEI\s*[:#-]?\s*)?(\d{15})\b", re.IGNORECASE)
EMPLOYEE_ID_RE = re.compile(r"\b(?:employee|staff)\s+id\s*[:#-]?\s*([A-Z0-9-]{4,20})\b", re.IGNORECASE)
CUSTOMER_ACCOUNT_RE = re.compile(
    r"\b(?:customer|client)\s+(?:id|account)\s*[:#-]?\s*([A-Z0-9-]{4,24})\b",
    re.IGNORECASE,
)
MEDICAL_RECORD_RE = re.compile(r"\b(?:MRN|medical\s+record)\s*[:#-]?\s*([A-Z0-9-]{4,24})\b", re.IGNORECASE)
UK_NATIONAL_INSURANCE_RE = re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.IGNORECASE)
UK_UTR_RE = re.compile(r"\b(?:UTR|unique\s+taxpayer\s+reference)\s*[:#-]?\s*(\d{10})\b", re.IGNORECASE)
UK_COMPANIES_HOUSE_RE = re.compile(
    r"\b(?:companies\s+house\s+(?:number|no\.?)|company\s+(?:number|no\.?)|CH\s+(?:number|no\.?))\s*[:#-]?\s*"
    r"([A-Z]{2}\d{6}|\d{8})\b",
    re.IGNORECASE,
)
UK_NHS_NUMBER_RE = re.compile(r"\bNHS\s+(?:number|no\.?)\s*[:#-]?\s*(\d{3}\s?\d{3}\s?\d{4})\b", re.IGNORECASE)
MY_MYKAD_RE = re.compile(
    r"\b(?:MyKad|MyPR|NRIC|I\.?(?:C|D)\.?(?:\s+(?:number|no\.?)?)?)\s*[:#-]?\s*(\d{6}-?\d{2}-?\d{4})\b",
    re.IGNORECASE,
)
MY_SSM_REGISTRATION_RE = re.compile(
    r"\b(?:SSM\s+)?(?:company|business|entity)?\s*registration\s*(?:number|no\.?)\s*[:#-]?\s*((?:19|20)\d{10})\b",
    re.IGNORECASE,
)
FINANCIAL_AMOUNT_RE = re.compile(
    r"\b(?:US\$|S\$|\$|EUR|GBP|JPY|CNY|HKD|AUD)\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:million|billion|m|bn))?\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"\b\d{1,3}(?:\.\d+)?%\b")
HIGH_RISK_RE = re.compile(
    r"\b(?:MNPI|material\s+non[- ]public|inside\s+information|earnings\s+before\s+release|"
    r"non[- ]public\s+results|confidential\s+(?:Q[1-4]\s+)?guidance|before\s+announcement|"
    r"selective\s+disclosure|blackout\s+period|tipping|definitive\s+agreement|"
    r"cybersecurity\s+incident|clinical\s+trial|reserve\s+estimate|settlement\s+term|"
    r"SSN|passport\s+number|credit\s+card)\b",
    re.IGNORECASE,
)
SPECIAL_CATEGORY_RE = re.compile(
    r"\b(?:religious\s+belief|trade\s+union|political\s+opinion|health\s+condition|"
    r"diagnosis|biometric|genetic|sexual\s+orientation|racial\s+origin|ethnic\s+origin)\b",
    re.IGNORECASE,
)
MINOR_RE = re.compile(r"\b(?:minor|child|under\s+(?:13|14|16|18)|age\s+(?:[0-9]|1[0-7]))\b", re.IGNORECASE)
CROSS_BORDER_RE = re.compile(
    r"\b(?:cross[- ]border|data\s+export|SCCs?|IDTA|adequacy|CAC\s+security\s+assessment|"
    r"ASEAN\s+MCCs|APEC\s+CBPR)\b",
    re.IGNORECASE,
)
CONSENT_ERASURE_RE = re.compile(
    r"\b(?:withdraw\s+consent|right\s+to\s+erasure|right\s+to\s+delete|DSAR|do\s+not\s+sell|objection)\b",
    re.IGNORECASE,
)
DATA_MINIMISATION_RE = re.compile(
    r"\b(?:data\s+minimi[sz]ation|minimum\s+necessary|over[- ]collection|purpose\s+limitation)\b",
    re.IGNORECASE,
)

DETECTOR_FAMILIES = [
    "universal_pii",
    "jurisdiction_specific_terms",
    "special_category_pii",
    "privacy_handling_events",
    "mnpi_lexicon",
    "financial_scalars",
    "placeholder_rewrite",
    "document_scrub",
]

PatternSpec = tuple[re.Pattern[str], str, str, str]


def review_text(
    text: str,
    *,
    source_jurisdiction: str,
    destination_jurisdiction: str,
) -> tuple[str, list[ReviewFinding]]:
    findings: list[ReviewFinding] = []
    source_pack = resolve_pack(source_jurisdiction)
    destination_pack = resolve_pack(destination_jurisdiction)
    for pattern, kind, severity, category in [
        (CLIENT_RE, "client_reference", "medium", "PII"),
        (ORG_RE, "organization", "medium", "PII"),
        (PERSON_RE, "person", "medium", "PII"),
        (EMAIL_RE, "email", "medium", "PII"),
        (PHONE_RE, "phone", "medium", "PII"),
        (NATIONAL_ID_RE, "national_id", "high", "PII"),
        (PASSPORT_RE, "passport_number", "high", "PII"),
        (BANK_ACCOUNT_RE, "bank_account", "high", "PII"),
        (DOB_RE, "date_of_birth", "high", "PII"),
        (MAC_RE, "mac_address", "medium", "PII"),
        (EMPLOYEE_ID_RE, "employee_id", "medium", "PII"),
        (CUSTOMER_ACCOUNT_RE, "customer_account_number", "medium", "PII"),
        (MEDICAL_RECORD_RE, "medical_record_number", "high", "PII"),
        (FINANCIAL_AMOUNT_RE, "financial_amount", "medium", "MNPI"),
        (PERCENT_RE, "percentage_scalar", "medium", "MNPI"),
        (HIGH_RISK_RE, "mnpi_or_high_risk_secret", "high", "MNPI"),
        (SPECIAL_CATEGORY_RE, "special_category_pii", "high", "PII"),
        (MINOR_RE, "minor_data_reference", "medium", "PII"),
        (CROSS_BORDER_RE, "cross_border_transfer_marker", "medium", "PII"),
        (CONSENT_ERASURE_RE, "consent_or_erasure_marker", "medium", "PII"),
        (DATA_MINIMISATION_RE, "data_minimisation_marker", "medium", "PII"),
    ]:
        findings.extend(
            _find(pattern, text, kind=kind, severity=severity, jurisdiction=source_pack.code, category=category)
        )
    findings.extend(
        _find_luhn(CREDIT_CARD_RE, text, kind="credit_card", severity="high", jurisdiction=source_pack.code)
    )
    findings.extend(_find_luhn(IMEI_RE, text, kind="imei", severity="high", jurisdiction=source_pack.code))
    findings.extend(_find_ip_addresses(text, jurisdiction=source_pack.code))
    if "UK" in {source_pack.code, destination_pack.code}:
        findings.extend(
            _find(
                UK_NATIONAL_INSURANCE_RE,
                text,
                kind="uk_national_insurance_number",
                severity="high",
                jurisdiction="UK",
                category="PII",
            )
        )
        findings.extend(
            _find(UK_UTR_RE, text, kind="uk_utr", severity="high", jurisdiction="UK", category="PII")
        )
        findings.extend(
            _find(
                UK_COMPANIES_HOUSE_RE,
                text,
                kind="uk_companies_house_number",
                severity="medium",
                jurisdiction="UK",
                category="PII",
            )
        )
        findings.extend(_find_uk_nhs_numbers(text))
    if "MY" in {source_pack.code, destination_pack.code}:
        findings.extend(
            _find(MY_MYKAD_RE, text, kind="my_mykad", severity="high", jurisdiction="MY", category="PII")
        )
        findings.extend(
            _find(
                MY_SSM_REGISTRATION_RE,
                text,
                kind="my_ssm_registration_number",
                severity="medium",
                jurisdiction="MY",
                category="PII",
            )
        )

    strict_terms = set(source_pack.strict_terms) | set(destination_pack.strict_terms)
    mnpi_terms = set(source_pack.mnpi_strict_terms) | set(destination_pack.mnpi_strict_terms)
    for term in strict_terms:
        for match in re.finditer(re.escape(term), text, flags=re.IGNORECASE):
            findings.append(
                ReviewFinding(
                    kind="jurisdiction_strict_term",
                    text=match.group(0),
                    severity="high" if term in mnpi_terms else "medium",
                    start=match.start(),
                    end=match.end(),
                    jurisdiction=destination_pack.code,
                    metadata={
                        "category": "MNPI" if term in mnpi_terms else "PII",
                        "source_statute": source_pack.pii_statute,
                        "destination_statute": destination_pack.pii_statute,
                    },
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


def anonymize_text(text: str) -> tuple[str, list[PlaceholderReplacement]]:
    replacements = _collect_replacements(text)
    output = text
    applied: list[PlaceholderReplacement] = []
    counters: dict[str, int] = {}
    offset = 0
    for start, end, entity_type, _original in replacements:
        counters[entity_type] = counters.get(entity_type, 0) + 1
        placeholder = f"[{entity_type}_{counters[entity_type]}]"
        adjusted_start = start + offset
        adjusted_end = end + offset
        output = output[:adjusted_start] + placeholder + output[adjusted_end:]
        offset += len(placeholder) - (end - start)
        applied.append(
            PlaceholderReplacement(
                placeholder=placeholder,
                entity_type=entity_type,
                start_char=start,
                end_char=end,
            )
        )
    return output, applied


def redact_text(text: str) -> tuple[str, list[OpaqueRedaction]]:
    replacements = _collect_replacements(text)
    output = text
    redactions: list[OpaqueRedaction] = []
    offset = 0
    for number, (start, end, _entity_type, _original) in enumerate(replacements, start=1):
        marker = f"[REDACTED_{number}]"
        adjusted_start = start + offset
        adjusted_end = end + offset
        output = output[:adjusted_start] + marker + output[adjusted_end:]
        offset += len(marker) - (end - start)
        redactions.append(OpaqueRedaction(marker=marker, start_char=start, end_char=end))
    return output, redactions


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
    metadata_findings = []
    lowered = decoded[:4096].lower()
    for marker in [b"/author", b"/creator", b"/producer", b"lastmodifiedby", b"core.xml"]:
        if marker in lowered:
            metadata_findings.append({"kind": "document_metadata", "marker": marker.decode("ascii", errors="ignore")})
    return {
        "document_base64": base64.b64encode(decoded).decode("ascii"),
        "metadata_findings": metadata_findings,
        "sha256": hashlib.sha256(decoded).hexdigest(),
    }


def _find(
    pattern: re.Pattern[str],
    text: str,
    *,
    kind: str,
    severity: str,
    jurisdiction: str,
    category: str,
) -> list[ReviewFinding]:
    return [
        ReviewFinding(
            kind=kind,
            text=match.group(0),
            severity=severity,
            start=match.start(),
            end=match.end(),
            jurisdiction=jurisdiction,
            metadata={"category": category, "rule": kind},
        )
        for match in pattern.finditer(text)
    ]


def _find_luhn(
    pattern: re.Pattern[str],
    text: str,
    *,
    kind: str,
    severity: str,
    jurisdiction: str,
) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for match in pattern.finditer(text):
        raw = match.group(1) if match.lastindex else match.group(0)
        digits = re.sub(r"\D", "", raw)
        if not _luhn_valid(digits):
            continue
        findings.append(
            ReviewFinding(
                kind=kind,
                text=match.group(0),
                severity=severity,
                start=match.start(),
                end=match.end(),
                jurisdiction=jurisdiction,
                metadata={"category": "PII", "rule": kind, "validator": "luhn"},
            )
        )
    return findings


def _find_ip_addresses(text: str, *, jurisdiction: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for match in IP_RE.finditer(text):
        try:
            ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        findings.append(
            ReviewFinding(
                kind="ip_address",
                text=match.group(0),
                severity="medium",
                start=match.start(),
                end=match.end(),
                jurisdiction=jurisdiction,
                metadata={"category": "PII", "rule": "ip_address", "validator": "ipaddress"},
            )
        )
    return findings


def _find_uk_nhs_numbers(text: str) -> list[ReviewFinding]:
    findings: list[ReviewFinding] = []
    for match in UK_NHS_NUMBER_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(1))
        if not _uk_nhs_number_valid(digits):
            continue
        findings.append(
            ReviewFinding(
                kind="uk_nhs_number",
                text=match.group(0),
                severity="high",
                start=match.start(),
                end=match.end(),
                jurisdiction="UK",
                metadata={"category": "PII", "rule": "uk_nhs_number", "validator": "nhs_mod11"},
            )
        )
    return findings


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
        (PASSPORT_RE, "PASSPORT"),
        (BANK_ACCOUNT_RE, "BANK_ACCOUNT"),
        (CREDIT_CARD_RE, "CARD"),
        (DOB_RE, "DOB"),
        (IP_RE, "IP"),
        (MAC_RE, "MAC"),
        (IMEI_RE, "IMEI"),
        (EMPLOYEE_ID_RE, "EMPLOYEE_ID"),
        (CUSTOMER_ACCOUNT_RE, "CUSTOMER_ACCOUNT"),
        (MEDICAL_RECORD_RE, "MEDICAL_RECORD"),
        (UK_NATIONAL_INSURANCE_RE, "UK_NI"),
        (UK_UTR_RE, "UK_UTR"),
        (UK_COMPANIES_HOUSE_RE, "UK_COMPANIES_HOUSE"),
        (UK_NHS_NUMBER_RE, "UK_NHS"),
        (MY_MYKAD_RE, "MY_MYKAD"),
        (MY_SSM_REGISTRATION_RE, "MY_SSM_REGISTRATION"),
        (FINANCIAL_AMOUNT_RE, "FINANCIAL_AMOUNT"),
        (PERCENT_RE, "PERCENT"),
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


def _luhn_valid(digits: str) -> bool:
    if len(digits) < 12:
        return False
    total = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _uk_nhs_number_valid(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit():
        return False
    expected = 11 - sum(int(value) * weight for value, weight in zip(digits[:9], range(10, 1, -1), strict=True)) % 11
    if expected == 11:
        expected = 0
    return expected != 10 and int(digits[-1]) == expected
