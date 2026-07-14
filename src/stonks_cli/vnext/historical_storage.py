from __future__ import annotations

import gzip
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory

_CHUNK_BYTES = 1024 * 1024


@dataclass(frozen=True)
class HistoricalStorageCompaction:
    destination: Path
    source_sha256: str
    source_bytes: int
    compressed_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.destination, Path) or not self.destination.is_absolute():
            raise ValueError("historical-storage destination is invalid")
        if not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64:
            raise ValueError("historical-storage source digest is invalid")
        if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (self.source_bytes, self.compressed_bytes)):
            raise ValueError("historical-storage sizes are invalid")
        if self.compressed_bytes >= self.source_bytes:
            raise ValueError("historical-storage compaction did not reduce size")


def compact_historical_storage(source: Path, destination: Path) -> HistoricalStorageCompaction:
    _validate_source(source)
    _validate_destination(destination)
    ensure_private_directory(destination.parent)
    temporary = destination.parent / f".{destination.name}.{os.urandom(16).hex()}.tmp"
    digest = hashlib.sha256()
    source_bytes = 0
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output_file:
            with gzip.GzipFile(filename="", mode="wb", fileobj=output_file, mtime=0) as compressed_file:
                while chunk := input_file.read(_CHUNK_BYTES):
                    digest.update(chunk)
                    source_bytes += len(chunk)
                    compressed_file.write(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
        compressed_bytes = temporary.stat().st_size
        if source_bytes == 0 or compressed_bytes >= source_bytes:
            raise ValueError("historical-storage compaction did not reduce size")
        os.link(temporary, destination)
        temporary.unlink()
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    enforce_private_file(destination)
    return HistoricalStorageCompaction(destination, digest.hexdigest(), source_bytes, compressed_bytes)


def _validate_source(source: Path) -> None:
    if not isinstance(source, Path) or not source.is_absolute() or source.is_symlink() or not source.is_file():
        raise ValueError("historical-storage source must be an absolute regular file")


def _validate_destination(destination: Path) -> None:
    if not isinstance(destination, Path) or not destination.is_absolute() or destination.is_symlink():
        raise ValueError("historical-storage destination must be an absolute non-symlink path")
    if destination.exists():
        raise FileExistsError(destination)
