# SPDX-License-Identifier: Apache-2.0
"""Solomon local jurisdiction packs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JurisdictionPack:
    code: str
    name: str
    strict_terms: tuple[str, ...]
    pii_statute: str = ""
    mnpi_statute: str = ""


JURISDICTION_PACKS: dict[str, JurisdictionPack] = {
    "SG": JurisdictionPack(
        code="SG",
        name="Singapore",
        strict_terms=("NRIC", "FIN", "SFA section 218", "inside information"),
        pii_statute="Personal Data Protection Act 2012",
        mnpi_statute="Securities and Futures Act 2001 ss215, 218, 219",
    ),
    "MY": JurisdictionPack(
        code="MY",
        name="Malaysia",
        strict_terms=("MyKad", "PDPA Malaysia", "CMSA sections 188-189"),
        pii_statute="Personal Data Protection Act 2010",
        mnpi_statute="Capital Markets and Services Act 2007 ss188-189",
    ),
    "ID": JurisdictionPack(
        code="ID",
        name="Indonesia",
        strict_terms=("NIK", "UU PDP", "OJK material information"),
        pii_statute="UU Pelindungan Data Pribadi No. 27/2022",
        mnpi_statute="OJK Regulation 31/POJK.04/2015 and Capital Market Law",
    ),
    "TH": JurisdictionPack(
        code="TH",
        name="Thailand",
        strict_terms=("Thai national ID", "PDPA B.E. 2562", "SEA section 241"),
        pii_statute="PDPA B.E. 2562 (2019)",
        mnpi_statute="Securities and Exchange Act B.E. 2535 ss241-243",
    ),
    "PH": JurisdictionPack(
        code="PH",
        name="Philippines",
        strict_terms=("Data Privacy Act", "TIN", "SRC section 27"),
        pii_statute="Data Privacy Act 2012",
        mnpi_statute="Securities Regulation Code section 27",
    ),
    "VN": JurisdictionPack(
        code="VN",
        name="Vietnam",
        strict_terms=("Decree 13/2023", "citizen identity card", "Law on Securities article 12"),
        pii_statute="Decree 13/2023/ND-CP",
        mnpi_statute="Law on Securities 2019 article 12",
    ),
    "HK": JurisdictionPack(
        code="HK",
        name="Hong Kong",
        strict_terms=("HKID", "PDPO", "SFO Part XIV"),
        pii_statute="Personal Data (Privacy) Ordinance Cap. 486",
        mnpi_statute="Securities and Futures Ordinance Part XIV",
    ),
    "AU": JurisdictionPack(
        code="AU",
        name="Australia",
        strict_terms=("TFN", "Privacy Act 1988", "Corporations Act 1042A"),
        pii_statute="Privacy Act 1988",
        mnpi_statute="Corporations Act 2001 ss1042A-1043O",
    ),
    "JP": JurisdictionPack(
        code="JP",
        name="Japan",
        strict_terms=("My Number", "APPI", "FIEA Article 166"),
        pii_statute="Act on the Protection of Personal Information",
        mnpi_statute="Financial Instruments and Exchange Act Arts 166-167",
    ),
    "KR": JurisdictionPack(
        code="KR",
        name="South Korea",
        strict_terms=("RRN", "PIPA", "FSCMA Article 174"),
        pii_statute="Personal Information Protection Act",
        mnpi_statute="Financial Investment Services and Capital Markets Act Arts 174-179",
    ),
    "US": JurisdictionPack(
        code="US",
        name="United States",
        strict_terms=("SSN", "Reg FD", "material non-public information", "HIPAA", "GLBA"),
        pii_statute="CCPA/CPRA, HIPAA, and GLBA",
        mnpi_statute="Exchange Act s10(b), Rule 10b-5, Reg FD",
    ),
    "UK": JurisdictionPack(
        code="UK",
        name="United Kingdom",
        strict_terms=("National Insurance", "UK MAR", "inside information"),
        pii_statute="UK GDPR and Data Protection Act 2018",
        mnpi_statute="UK Market Abuse Regulation Article 7",
    ),
    "EU": JurisdictionPack(
        code="EU",
        name="European Union",
        strict_terms=("MAR Article 7", "inside information", "GDPR special category"),
        pii_statute="GDPR",
        mnpi_statute="EU Market Abuse Regulation 596/2014 Article 7",
    ),
    "SEA": JurisdictionPack(
        code="SEA",
        name="Southeast Asia baseline",
        strict_terms=("ASEAN MCCs", "cross-border transfer", "inside information"),
        pii_statute="ASEAN privacy baseline",
        mnpi_statute="ASEAN capital-markets baseline",
    ),
    "IN": JurisdictionPack(
        code="IN",
        name="India",
        strict_terms=("Aadhaar", "PAN", "DPDPA", "SEBI PIT"),
        pii_statute="Digital Personal Data Protection Act 2023",
        mnpi_statute="SEBI PIT Regulations 2015",
    ),
    "CN": JurisdictionPack(
        code="CN",
        name="China",
        strict_terms=("PIPL", "CAC", "resident identity card", "Securities Law Article 52"),
        pii_statute="Personal Information Protection Law",
        mnpi_statute="China Securities Law Arts 50-54",
    ),
    "AE": JurisdictionPack(
        code="AE",
        name="United Arab Emirates",
        strict_terms=("PDPL", "DIFC DPL", "ADGM Data Protection"),
        pii_statute="UAE Federal Decree-Law 45/2021",
        mnpi_statute="UAE SCA regulations",
    ),
    "SA": JurisdictionPack(
        code="SA",
        name="Saudi Arabia",
        strict_terms=("PDPL", "SDAIA", "CMA Market Conduct"),
        pii_statute="KSA Personal Data Protection Law",
        mnpi_statute="Saudi CMA Market Conduct Regulations",
    ),
}


def resolve_pack(code: str) -> JurisdictionPack:
    normalized = code.upper()
    return JURISDICTION_PACKS.get(normalized, JurisdictionPack(code=normalized, name=normalized, strict_terms=()))


def supported_jurisdiction_codes() -> list[str]:
    return sorted(JURISDICTION_PACKS)
