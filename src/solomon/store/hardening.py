# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re

from solomon.api.schemas import SolomonModel
from solomon.currency.models import KnowledgeContentRole

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
INSTRUCTION_PATTERNS = [
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|rules)\b", re.IGNORECASE),
    re.compile(r"\b(?:system|developer)\s+(?:prompt|message|instruction)s?\b", re.IGNORECASE),
    re.compile(r"\bjailbreak\b", re.IGNORECASE),
    re.compile(r"\bdo\s+not\s+follow\s+(?:the\s+)?(?:policy|instructions|rules)\b", re.IGNORECASE),
    re.compile(r"\bact\s+as\s+(?:an?\s+)?(?:system|developer|admin)\b", re.IGNORECASE),
]


class StoredContentHardeningResult(SolomonModel):
    content: str
    content_role: KnowledgeContentRole
    findings: list[str]


def harden_stored_content(content: str) -> StoredContentHardeningResult:
    findings: list[str] = []
    normalized = CONTROL_RE.sub(" ", content)
    if normalized != content:
        findings.append("control_characters_normalized")
    if any(pattern.search(normalized) for pattern in INSTRUCTION_PATTERNS):
        findings.append("instruction_like_content_detected")
        role = KnowledgeContentRole.INSTRUCTION
    else:
        role = KnowledgeContentRole.POSITION
    return StoredContentHardeningResult(content=" ".join(normalized.split()), content_role=role, findings=findings)
