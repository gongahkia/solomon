from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime


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
