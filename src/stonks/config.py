from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def default_config_path() -> Path:
    return Path.home() / ".config" / "stonks" / "config.json"


class ScheduleConfig(BaseModel):
    cron: str = Field(default="0 17 * * 1-5", description="Crontab string")
    timezone: str = Field(default="local", description="Timezone name or 'local'")


class ModelConfig(BaseModel):
    backend: Literal["ollama", "transformers", "onnx"] = "ollama"
    model: str = "gemma3"
    host: str = "http://localhost:11434"


class DataConfig(BaseModel):
    provider: Literal["stooq", "csv"] = "stooq"
    csv_path: str | None = None
    cache_ttl_seconds: int = Field(default=3600, ge=0)


class TickerOverride(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)


class AppConfig(BaseModel):
    tickers: list[str] = Field(default_factory=lambda: ["AAPL.US", "MSFT.US"])
    data: DataConfig = Field(default_factory=DataConfig)
    ticker_overrides: dict[str, TickerOverride] = Field(default_factory=dict)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)


def config_path() -> Path:
    env = os.getenv("STONKS_CONFIG")
    return Path(env).expanduser() if env else default_config_path()


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)


def save_default_config(path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig()
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return path
