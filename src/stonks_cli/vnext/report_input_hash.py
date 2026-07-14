from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass

_SOURCE_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReportInputHash:
    source_id: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("report-input hash source ID is invalid")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("report-input hash digest is invalid")
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or self.byte_count < 2:
            raise ValueError("report-input hash byte count is invalid")

    def to_data(self) -> dict[str, object]:
        return {"source_id": self.source_id, "sha256": self.sha256, "byte_count": self.byte_count}


def hash_report_input_data(source_id: str, data: Mapping[str, object]) -> ReportInputHash:
    if not isinstance(source_id, str) or not _SOURCE_ID_PATTERN.fullmatch(source_id):
        raise ValueError("report-input source ID is invalid")
    if not isinstance(data, Mapping):
        raise TypeError("report-input data must be an object")
    canonical_data = _canonicalize_json(data)
    encoded = json.dumps(canonical_data, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return ReportInputHash(source_id, hashlib.sha256(encoded).hexdigest(), len(encoded))


def _canonicalize_json(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("report-input data contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("report-input data keys must be strings")
        return {key: _canonicalize_json(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json(item) for item in value]
    raise ValueError("report-input data must contain JSON-safe values")
