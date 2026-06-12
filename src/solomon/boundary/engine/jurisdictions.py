# SPDX-License-Identifier: Apache-2.0
"""Kaypoh-derived local jurisdiction packs vendored into Solomon."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JurisdictionPack:
    code: str
    name: str
    strict_terms: tuple[str, ...]


JURISDICTION_PACKS: dict[str, JurisdictionPack] = {
    "SG": JurisdictionPack(
        code="SG",
        name="Singapore",
        strict_terms=("NRIC", "FIN", "SFA section 218", "inside information"),
    ),
    "US": JurisdictionPack(
        code="US",
        name="United States",
        strict_terms=("SSN", "Reg FD", "material non-public information"),
    ),
    "UK": JurisdictionPack(
        code="UK",
        name="United Kingdom",
        strict_terms=("National Insurance", "UK MAR", "inside information"),
    ),
    "EU": JurisdictionPack(
        code="EU",
        name="European Union",
        strict_terms=("MAR Article 7", "inside information", "GDPR special category"),
    ),
}


def resolve_pack(code: str) -> JurisdictionPack:
    normalized = code.upper()
    return JURISDICTION_PACKS.get(normalized, JurisdictionPack(code=normalized, name=normalized, strict_terms=()))
