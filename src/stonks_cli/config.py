from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from stonks_cli.logging_utils import log_suppressed_exception


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
    provider: Literal["stooq", "csv", "plugin", "yfinance", "tiger", "finnhub", "alpaca", "polymarket"] = "stooq"
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


class ApiKeysConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    tiger_id: str | None = None
    tiger_account: str | None = None
    tiger_private_key_path: str | None = None
    finnhub_api_key: str | None = None
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True


class PolymarketConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = Field(default=False)
    private_key_env: str = Field(default="POLYMARKET_PRIVATE_KEY")
    api_key_env: str = Field(default="POLYMARKET_API_KEY")
    api_secret_env: str = Field(default="POLYMARKET_API_SECRET")
    api_passphrase_env: str = Field(default="POLYMARKET_API_PASSPHRASE")
    signature_type: Literal["proxy", "eoa", "gnosis-safe"] = "proxy"
    chain_id: int = Field(default=137, ge=1)
    scanner_limit: int = Field(default=200, ge=1, le=1000)
    min_market_liquidity_usd: float = Field(default=50000.0, ge=0.0)
    min_book_depth_usd: float = Field(default=500.0, ge=0.0)
    min_hours_to_resolution: float = Field(default=4.0, ge=0.0)
    max_hours_to_resolution: float = Field(default=168.0, ge=0.0)
    require_active: bool = True
    paper: bool = True
    loop_interval_ms: int = Field(default=1000, ge=100, le=60000)
    paper_starting_cash: float = Field(default=1000.0, ge=0.0)
    max_position_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    max_market_notional: float = Field(default=0.0, ge=0.0)
    min_cash_reserve_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    max_open_positions: int = Field(default=5, ge=0, le=1000)
    auto_trade_enabled: bool = False
    auto_trade_min_score: float = Field(default=12.0, ge=0.0)
    auto_trade_min_target_wallets: int = Field(default=1, ge=0, le=1000)
    auto_exit_enabled: bool = True
    take_profit_price_delta: float = Field(default=0.10, ge=0.0, le=1.0)
    stop_loss_price_delta: float = Field(default=0.08, ge=0.0, le=1.0)
    stale_position_hours: float = Field(default=24.0, ge=0.0)
    live_post_only: bool = True
    live_order_max_age_seconds: int = Field(default=30, ge=1, le=86400)
    max_live_open_orders: int = Field(default=20, ge=0, le=100000)
    max_daily_loss: float = Field(default=0.0, ge=0.0)
    max_consecutive_live_errors: int = Field(default=3, ge=1, le=1000)
    max_consecutive_stream_errors: int = Field(default=5, ge=1, le=1000)
    live_require_armed_env: bool = True
    live_armed_env: str = Field(default="STONKS_CLI_POLYMARKET_LIVE_ARMED")
    rust_hotpath_enabled: bool = False
    rust_hotpath_use_cargo: bool = False


class TuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    refresh_interval: int = Field(default=60, ge=5, le=3600)
    theme: Literal["dark", "light"] = "dark"
    default_view: str = "dashboard"


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
    deterministic: bool = Field(
        default=False, description="Use deterministic execution (stable ordering, no concurrency)"
    )
    seed: int = Field(default=0, description="Seed value for deterministic mode")
    watchlists: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Named ticker sets (e.g. {'tech': ['AAPL.US', 'MSFT.US']})",
    )
    webhook_url: str | None = Field(
        default=None,
        description="Optional webhook URL for alert notifications",
    )
    api_keys: ApiKeysConfig = Field(default_factory=ApiKeysConfig)
    polymarket: PolymarketConfig = Field(default_factory=PolymarketConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)


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
                "ticker_overrides": {normalize_ticker(k): v for k, v in (cfg.ticker_overrides or {}).items()},
                "watchlists": normalized_watchlists,
            }
        )
    except Exception as e:
        log_suppressed_exception(context="config.normalize_load", error=e, config_path=path)
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
