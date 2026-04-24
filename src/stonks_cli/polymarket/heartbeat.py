from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from stonks_cli.config import AppConfig
from stonks_cli.logging_utils import log_suppressed_exception
from stonks_cli.paths import default_state_dir
from stonks_cli.polymarket.auth import authenticated_clob_client
from stonks_cli.polymarket.client import utc_now_iso


@dataclass(frozen=True)
class HeartbeatState:
    heartbeat_id: str = ""
    last_sent_at: str | None = None


def heartbeat_state_path() -> Path:
    return default_state_dir() / "polymarket_heartbeat.json"


def load_heartbeat_state() -> HeartbeatState:
    path = heartbeat_state_path()
    if not path.exists():
        return HeartbeatState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        log_suppressed_exception(context="polymarket.heartbeat.load", error=e, path=path)
        return HeartbeatState()
    return HeartbeatState(
        heartbeat_id=str(payload.get("heartbeat_id") or ""),
        last_sent_at=payload.get("last_sent_at"),
    )


def save_heartbeat_state(state: HeartbeatState) -> None:
    path = heartbeat_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def maybe_send_heartbeat(cfg: AppConfig, *, force: bool = False, client: object | None = None) -> dict[str, object] | None:
    if cfg.polymarket.paper or not cfg.polymarket.live_heartbeat_enabled:
        return None
    state = load_heartbeat_state()
    if not force and state.last_sent_at is not None:
        age = _seconds_since(state.last_sent_at)
        if age is not None and age < cfg.polymarket.live_heartbeat_interval_seconds:
            return None
    use_client = client
    if use_client is None:
        use_client, _ = authenticated_clob_client(cfg)
    response = _post_heartbeat(use_client, heartbeat_id=state.heartbeat_id)
    heartbeat_id = _extract_heartbeat_id(response) or state.heartbeat_id
    updated = HeartbeatState(heartbeat_id=heartbeat_id, last_sent_at=utc_now_iso())
    save_heartbeat_state(updated)
    return {
        "heartbeat_id": heartbeat_id,
        "response": response,
        "last_sent_at": updated.last_sent_at,
    }


def has_heartbeat_method(client: object) -> bool:
    return any(hasattr(client, name) for name in ("post_heartbeat", "heartbeat", "postHeartbeat"))


def _post_heartbeat(client: object, *, heartbeat_id: str) -> object:
    attempts = (
        ("post_heartbeat", {"heartbeat_id": heartbeat_id}),
        ("heartbeat", {"heartbeat_id": heartbeat_id}),
        ("postHeartbeat", {"heartbeatId": heartbeat_id}),
        ("postHeartbeat", {"heartbeat_id": heartbeat_id}),
    )
    for method_name, kwargs in attempts:
        method = getattr(client, method_name, None)
        if method is None:
            continue
        try:
            return method(**kwargs)
        except TypeError:
            continue
    raise AttributeError("live client does not expose a supported heartbeat method")


def _extract_heartbeat_id(response: object) -> str | None:
    if isinstance(response, dict):
        for key in ("heartbeat_id", "heartbeatId"):
            value = response.get(key)
            if value not in (None, ""):
                return str(value)
    for key in ("heartbeat_id", "heartbeatId"):
        value = getattr(response, key, None)
        if value not in (None, ""):
            return str(value)
    return None


def _seconds_since(raw_ts: str) -> float | None:
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.fromisoformat(utc_now_iso().replace("Z", "+00:00"))
    return max(0.0, (now - parsed).total_seconds())
