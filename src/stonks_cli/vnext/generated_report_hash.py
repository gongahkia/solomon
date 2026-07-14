from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_CHUNK_BYTES = 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class GeneratedReportHash:
    path: Path
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("generated-report hash path is invalid")
        if not isinstance(self.sha256, str) or not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("generated-report hash digest is invalid")
        if not isinstance(self.byte_count, int) or isinstance(self.byte_count, bool) or self.byte_count < 0:
            raise ValueError("generated-report hash byte count is invalid")

    def to_data(self) -> dict[str, object]:
        return {"path": str(self.path), "sha256": self.sha256, "byte_count": self.byte_count}


def hash_generated_report(path: Path) -> GeneratedReportHash:
    if not isinstance(path, Path) or not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("generated report must be an absolute regular file")
    before = path.stat()
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as report:
        while chunk := report.read(_CHUNK_BYTES):
            digest.update(chunk)
            byte_count += len(chunk)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("generated report changed while hashing")
    return GeneratedReportHash(path, digest.hexdigest(), byte_count)
