from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def default_config_path() -> Path:
    from stonks_cli.paths import default_config_path as _default_config_path

    return _default_config_path()


class ScheduleConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    cron: str = Field(default="0 17 * * 1-5", description="Crontab string")
    timezone: str = Field(default="local", description="Timezone name or 'local'")

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


class DataConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider: Literal["stooq", "csv", "plugin", "yfinance"] = "stooq"
    csv_path: str | None = None
    plugin_name: str | None = Field(default=None, description="Provider key when provider='plugin'")
    cache_ttl_seconds: int = Field(default=3600, ge=0)
    concurrency_limit: int = Field(default=8, ge=1, le=64)


class RiskConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    max_position_fraction: float = Field(default=0.20, ge=0.0, le=1.0)
    max_portfolio_exposure_fraction: float = Field(default=1.00, ge=0.0, le=1.0)
    min_history_days: int = Field(default=60, ge=1)


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    fee_bps: float = Field(default=0.0, ge=0.0, description="Per-trade fee in basis points")
    slippage_bps: float = Field(default=0.0, ge=0.0, description="Per-trade slippage in basis points")


class TickerOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: DataConfig = Field(default_factory=DataConfig)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tickers: list[str] = Field(default_factory=lambda: ["AAPL.US", "MSFT.US"])
    data: DataConfig = Field(default_factory=DataConfig)
    ticker_overrides: dict[str, TickerOverride] = Field(default_factory=dict)
    plugins: list[str] = Field(default_factory=list, description="Plugin module names or .py file paths")
    strategy: str = Field(default="basic_trend_rsi")
    strategy_params: dict[str, object] = Field(
        default_factory=dict,
        description="Optional tuning knobs for built-in strategies (e.g. fast/slow windows)",
    )
    risk: RiskConfig = Field(default_factory=RiskConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    deterministic: bool = Field(default=False, description="Use deterministic execution (stable ordering, no concurrency)")
    seed: int = Field(default=0, description="Seed value for deterministic mode")
    watchlists: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Named ticker sets (e.g. {'tech': ['AAPL.US', 'MSFT.US']})",
    )
    webhook_url: str | None = Field(
        default=None,
        description="Optional webhook URL for alert notifications",
    )


def config_path() -> Path:
    env = os.getenv("STONKS_CLI_CONFIG")
    return Path(env).expanduser() if env else default_config_path()


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    cfg = AppConfig.model_validate(data)
    # Normalize tickers and override keys at the boundary.
    try:
        from stonks_cli.data.providers import normalize_ticker

        normalized_watchlists: dict[str, list[str]] = {}
        for name, tickers in (cfg.watchlists or {}).items():
            if not isinstance(name, str) or not name.strip():
                continue
            normalized_watchlists[name] = [normalize_ticker(t) for t in (tickers or [])]

        cfg = cfg.model_copy(
            update={
                "tickers": [normalize_ticker(t) for t in cfg.tickers],
                "ticker_overrides": {
                    normalize_ticker(k): v for k, v in (cfg.ticker_overrides or {}).items()
                },
                "watchlists": normalized_watchlists,
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
