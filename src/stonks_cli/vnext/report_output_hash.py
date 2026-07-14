from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_REPORT_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReportOutputHash:
    report_id: str
    sha256: str
    character_count: int
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.report_id, str) or not _REPORT_ID_PATTERN.fullmatch(self.report_id):
            raise ValueError("report-output hash report ID is invalid")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("report-output hash digest is invalid")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (self.character_count, self.byte_count)):
            raise ValueError("report-output hash sizes are invalid")

    def to_data(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "sha256": self.sha256,
            "character_count": self.character_count,
            "byte_count": self.byte_count,
        }


def hash_report_output_data(report_id: str, rendered_output: str) -> ReportOutputHash:
    if not isinstance(report_id, str) or not _REPORT_ID_PATTERN.fullmatch(report_id):
        raise ValueError("report-output report ID is invalid")
    if not isinstance(rendered_output, str):
        raise TypeError("report-output data must be text")
    encoded = rendered_output.encode("utf-8")
    return ReportOutputHash(report_id, hashlib.sha256(encoded).hexdigest(), len(rendered_output), len(encoded))
