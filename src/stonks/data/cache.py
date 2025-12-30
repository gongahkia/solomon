from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path


def default_cache_dir() -> Path:
    return Path.home() / ".cache" / "stonks"


def _key_to_name(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
    return digest


@dataclass(frozen=True)
class CacheEntry:
    created_at: float
    payload: str


def load_cached_text(cache_dir: Path, key: str, ttl_seconds: int) -> str | None:
    path = cache_dir / f"{_key_to_name(key)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        created_at = float(data.get("created_at", 0))
        payload = data.get("payload")
        if not isinstance(payload, str):
            return None
        if ttl_seconds > 0 and (time.time() - created_at) > ttl_seconds:
            return None
        return payload
    except Exception:
        return None


def save_cached_text(cache_dir: Path, key: str, payload: str) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{_key_to_name(key)}.json"
    body = {"created_at": time.time(), "payload": payload}
    path.write_text(json.dumps(body), encoding="utf-8")
