from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from stonks_cli.vnext.crypto_universe_snapshot import CryptoUniverseSnapshot
from stonks_cli.vnext.filesystem import PRIVATE_FILE_MODE, enforce_private_file, ensure_private_directory

CRYPTO_UNIVERSE_HISTORY_VERSION = 1


@dataclass(frozen=True)
class CryptoUniverseHistory:
    snapshots: tuple[CryptoUniverseSnapshot, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshots, tuple) or not self.snapshots or not all(
            isinstance(snapshot, CryptoUniverseSnapshot) for snapshot in self.snapshots
        ):
            raise ValueError("crypto universe history snapshots are invalid")
        if len({snapshot.snapshot_id for snapshot in self.snapshots}) != len(self.snapshots):
            raise ValueError("crypto universe history snapshot IDs must be unique")
        timestamps = tuple(snapshot.captured_at for snapshot in self.snapshots)
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            raise ValueError("crypto universe history snapshots must be chronological")
        if len({snapshot.batch.provider_id for snapshot in self.snapshots}) != 1:
            raise ValueError("crypto universe history snapshots must use one provider")

    def to_data(self) -> dict[str, object]:
        return {"version": CRYPTO_UNIVERSE_HISTORY_VERSION, "snapshots": [snapshot.to_data() for snapshot in self.snapshots]}

    @classmethod
    def from_data(cls, data: object) -> CryptoUniverseHistory:
        if not isinstance(data, dict) or set(data) != {"version", "snapshots"} or data["version"] != CRYPTO_UNIVERSE_HISTORY_VERSION:
            raise ValueError("crypto universe history fields are invalid")
        if not isinstance(data["snapshots"], list):
            raise ValueError("crypto universe history snapshots are invalid")
        try:
            return cls(tuple(CryptoUniverseSnapshot.from_data(snapshot) for snapshot in data["snapshots"]))
        except (TypeError, ValueError) as error:
            raise ValueError("crypto universe history is malformed") from error


def append_crypto_universe_history(path: Path, snapshot: CryptoUniverseSnapshot) -> CryptoUniverseHistory:
    if not isinstance(snapshot, CryptoUniverseSnapshot):
        raise TypeError("crypto universe snapshot is required")
    try:
        history = load_crypto_universe_history(path)
    except FileNotFoundError:
        history = None
    updated = CryptoUniverseHistory((snapshot,)) if history is None else CryptoUniverseHistory(history.snapshots + (snapshot,))
    save_crypto_universe_history(path, updated)
    return updated


def save_crypto_universe_history(path: Path, history: CryptoUniverseHistory) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("crypto universe history path must be absolute")
    if not isinstance(history, CryptoUniverseHistory):
        raise TypeError("crypto universe history is required")
    if path.is_symlink():
        raise ValueError("crypto universe history path must not be a symlink")
    ensure_private_directory(path.parent)
    temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, PRIVATE_FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(history.to_data(), output, allow_nan=False, separators=(",", ":"), sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise
    enforce_private_file(path)
    return path


def load_crypto_universe_history(path: Path) -> CryptoUniverseHistory:
    if not isinstance(path, Path) or not path.is_absolute():
        raise ValueError("crypto universe history path must be absolute")
    enforce_private_file(path)
    try:
        return CryptoUniverseHistory.from_data(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError("crypto universe history cannot be loaded") from error


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
