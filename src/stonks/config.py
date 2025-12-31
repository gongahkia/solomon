from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def default_config_path() -> Path:
    return Path.home() / ".config" / "stonks" / "config.json"


class ScheduleConfig(BaseModel):
    cron: str = Field(default="0 17 * * 1-5", description="Crontab string")

    @field_validator("cron")
    @classmethod
    def validate_cron(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("cron must be non-empty")
        # Best-effort validation for crontab syntax.
        from apscheduler.triggers.cron import CronTrigger

        CronTrigger.from_crontab(v)
        return v
    timezone: str = Field(default="local", description="Timezone name or 'local'")


class ModelConfig(BaseModel):
    backend: Literal["ollama", "transformers", "onnx"] = "ollama"
    model: str = "gemma3"
    host: str = "http://localhost:11434"
    path: str | None = Field(default=None, description="Local model path (transformers/onnx)")


class DataConfig(BaseModel):
    provider: Literal["stooq", "csv"] = "stooq"
    csv_path: str | None = None
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    concurrency_limit: int = Field(default=8, ge=1, le=64)


class RiskConfig(BaseModel):
    max_position_fraction: float = Field(default=0.20, ge=0.0, le=1.0)
    max_portfolio_exposure_fraction: float = Field(default=1.00, ge=0.0, le=1.0)
    min_history_days: int = Field(default=60, ge=1)


class TickerOverride(BaseModel):
    data: DataConfig = Field(default_factory=DataConfig)


class AppConfig(BaseModel):
    tickers: list[str] = Field(default_factory=lambda: ["AAPL.US", "MSFT.US"])
    data: DataConfig = Field(default_factory=DataConfig)
    ticker_overrides: dict[str, TickerOverride] = Field(default_factory=dict)
    strategy: str = Field(default="basic_trend_rsi")
    risk: RiskConfig = Field(default_factory=RiskConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    deterministic: bool = Field(default=False, description="Use deterministic execution (stable ordering, no concurrency)")
    seed: int = Field(default=0, description="Seed value for deterministic mode")


def config_path() -> Path:
    env = os.getenv("STONKS_CONFIG")
    return Path(env).expanduser() if env else default_config_path()


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = AppConfig.model_validate(data)
    # Normalize tickers and override keys at the boundary.
    try:
        from stonks.data.providers import normalize_ticker

        cfg = cfg.model_copy(
            update={
                "tickers": [normalize_ticker(t) for t in cfg.tickers],
                "ticker_overrides": {
                    normalize_ticker(k): v for k, v in (cfg.ticker_overrides or {}).items()
                },
            }
        )
    except Exception:
        pass
    return cfg


def save_default_config(path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = AppConfig()
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return path


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
    return path


def update_config_field(cfg: AppConfig, dotted_path: str, value) -> AppConfig:
    """Update a nested config field using a dotted path like 'schedule.cron'."""

    dotted_path = (dotted_path or "").strip()
    if not dotted_path:
        raise ValueError("field path must be non-empty")

    data = cfg.model_dump(mode="json")
    parts = dotted_path.split(".")
    cur = data
    for p in parts[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            raise KeyError(f"unknown config path: {dotted_path}")
        cur = cur[p]
    leaf = parts[-1]
    if not isinstance(cur, dict) or leaf not in cur:
        raise KeyError(f"unknown config path: {dotted_path}")
    cur[leaf] = value
    return AppConfig.model_validate(data)
