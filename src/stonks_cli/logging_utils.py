from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LoggingConfig:
    verbose: int = 0
    quiet: bool = False
    structured: bool = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _events_path() -> Path:
    from stonks_cli.paths import default_state_dir

    return default_state_dir() / "events.jsonl"


def track_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "event": event,
        **{k: _json_safe(v) for k, v in fields.items()},
    }

    logger = logging.getLogger("stonks_cli.events")
    logger.log(level, "%s %s", event, json.dumps(payload, ensure_ascii=False, sort_keys=True))

    try:
        path = _events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        logging.getLogger(__name__).debug("failed writing events log", exc_info=True)


def log_suppressed_exception(
    *,
    context: str,
    error: Exception,
    level: int = logging.WARNING,
    **fields: Any,
) -> None:
    track_event(
        "suppressed_exception",
        level=level,
        context=context,
        error_type=type(error).__name__,
        error=str(error),
        **fields,
    )
    logging.getLogger("stonks_cli.errors").log(
        level,
        "%s: %s",
        context,
        error,
        exc_info=(type(error), error, error.__traceback__),
    )


def configure_logging(cfg: LoggingConfig) -> None:
    if cfg.quiet:
        level = logging.ERROR
    else:
        level = logging.INFO
        if cfg.verbose >= 1:
            level = logging.DEBUG

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(level)
    if cfg.structured:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
