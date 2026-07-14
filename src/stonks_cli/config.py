from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

CONFIG_SCHEMA_VERSION = 2
REDACTED_CONFIG_VALUE = "***REDACTED***"
_SENSITIVE_CONFIG_KEY_MARKERS = (
    "token",
    "secret",
    "passphrase",
    "private_key",
    "api_key",
    "password",
    "smtp_url",
    "authorization",
    "credential",
    "cookie",
    "webhook",
)


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
    provider: Literal["stooq", "csv", "plugin", "yfinance", "akshare", "tiger", "finnhub", "alpaca", "polymarket"] = "stooq"
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
    min_entry_price: float = Field(default=0.0, ge=0.0, le=1.0)
    max_spread_bps: float = Field(default=1000.0, ge=0.0)
    slippage_check_notional_usd: float = Field(default=5.0, ge=0.0)
    max_entry_slippage_bps: float = Field(default=300.0, ge=0.0)
    require_full_fill_estimate: bool = True
    min_hours_to_resolution: float = Field(default=4.0, ge=0.0)
    max_hours_to_resolution: float = Field(default=168.0, ge=0.0)
    require_active: bool = True
    allowed_market_keywords: list[str] = Field(default_factory=list)
    blocked_market_keywords: list[str] = Field(default_factory=list)
    allowed_market_slugs: list[str] = Field(default_factory=list)
    blocked_market_slugs: list[str] = Field(default_factory=list)
    crypto_only: bool = False
    block_sports: bool = False
    target_wallet_addresses: list[str] = Field(default_factory=list)
    wallet_copy_allowed_categories: list[str] = Field(default_factory=list)
    wallet_copy_blocked_categories: list[str] = Field(default_factory=list)
    paper: bool = True
    loop_interval_ms: int = Field(default=1000, ge=100, le=60000)
    paper_starting_cash: float = Field(default=1000.0, ge=0.0)
    max_position_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    max_market_notional: float = Field(default=0.0, ge=0.0)
    max_total_notional: float = Field(default=0.0, ge=0.0)
    min_cash_reserve_fraction: float = Field(default=0.10, ge=0.0, le=1.0)
    max_open_positions: int = Field(default=5, ge=0, le=1000)
    auto_trade_enabled: bool = False
    auto_trade_min_score: float = Field(default=12.0, ge=0.0)
    auto_trade_min_target_wallets: int = Field(default=1, ge=0, le=1000)
    consensus_enabled: bool = True
    consensus_min_buy_votes: int = Field(default=2, ge=1, le=3)
    consensus_single_vote_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    consensus_arbitrage_min_deviation_bps: float = Field(default=700.0, ge=0.0)
    auto_exit_enabled: bool = True
    volume_spike_exit_enabled: bool = True
    volume_spike_multiplier: float = Field(default=3.0, ge=1.0)
    volume_spike_min_delta_usd: float = Field(default=500.0, ge=0.0)
    take_profit_price_delta: float = Field(default=0.10, ge=0.0, le=1.0)
    stop_loss_price_delta: float = Field(default=0.08, ge=0.0, le=1.0)
    stale_position_hours: float = Field(default=24.0, ge=0.0)
    live_post_only: bool = True
    live_order_max_age_seconds: int = Field(default=30, ge=1, le=86400)
    live_min_order_notional_usd: float = Field(default=5.0, ge=0.0)
    max_live_open_orders: int = Field(default=20, ge=0, le=100000)
    max_daily_loss: float = Field(default=0.0, ge=0.0)
    max_daily_profit: float = Field(default=0.0, ge=0.0)
    stop_loss_reentry_cooldown_minutes: float = Field(default=60.0, ge=0.0)
    max_consecutive_live_errors: int = Field(default=3, ge=1, le=1000)
    max_consecutive_stream_errors: int = Field(default=5, ge=1, le=1000)
    live_heartbeat_enabled: bool = True
    live_heartbeat_interval_seconds: int = Field(default=5, ge=1, le=300)
    live_require_armed_env: bool = True
    live_armed_env: str = Field(default="STONKS_CLI_POLYMARKET_LIVE_ARMED")
    rust_hotpath_enabled: bool = False
    rust_hotpath_use_cargo: bool = False
    kelly_sizing_enabled: bool = False # opt-in fractional-Kelly sizing using wallet win-rate
    kelly_fraction: float = Field(default=0.25, ge=0.0, le=1.0) # 1/4 Kelly default
    use_microprice_for_entry: bool = False # use Stoikov microprice instead of midpoint as entry reference
    hurst_filter_enabled: bool = False # filter out non-mean-reverting markets at scan time
    hurst_max: float = Field(default=0.45, ge=0.0, le=1.0) # only accept markets with hurst < this (mean-reverting)
    vol_target_enabled: bool = False # carver-style inverse-vol sizing fallback when no wallet signal
    vol_target_per_trade: float = Field(default=0.05, ge=0.0, le=1.0) # max equity at risk per trade
    whale_trade_min_usd: float = Field(default=10000.0, ge=0.0) # threshold for whale-trade alerts


class WhaleMirrorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    venue: Literal["hyperliquid"] = "hyperliquid"
    paper: bool = True
    decision_ledger_path: str = "docs/decision-ledger.md"
    live_require_armed_env: bool = True
    hyperliquid_live_armed_env: str = "STONKS_CLI_HYPERLIQUID_LIVE_ARMED"
    live_phase1_budget_usd: float = Field(default=200.0, ge=0.0)
    max_live_order_notional_usd: float = Field(default=50.0, ge=0.0)
    scale_gate_green_weeks: int = Field(default=7, ge=1)


class CarryMirrorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    paper: bool = True
    live_armed: bool = False
    live_armed_env: str = "STONKS_CLI_CARRY_LIVE_ARMED"
    live_secrets_path: str = "~/.config/stonks-cli/carry-live.env"
    tiny_live_min_usd: float = Field(default=50.0, ge=0.0)
    tiny_live_max_usd: float = Field(default=200.0, ge=0.0)
    max_total_live_usd: float = Field(default=0.0, ge=0.0)
    max_delta_abs: float = Field(default=0.000001, ge=0.0)
    min_margin_buffer: float = Field(default=0.20, ge=0.0)
    min_liquidation_distance: float = Field(default=0.15, ge=0.0)
    max_data_age_seconds: float = Field(default=30.0, ge=0.0)
    daily_drawdown_limit_pct: float = Field(default=0.005, ge=0.0)
    weekly_drawdown_limit_pct: float = Field(default=0.015, ge=0.0)
    global_drawdown_limit_pct: float = Field(default=0.03, ge=0.0)
    min_net_apr: float = Field(
        default=0.15,
        ge=0.0,
        description="Research threshold only; not a profit claim.",
    )
    alert_sink: Literal["disabled", "telegram", "email"] = "disabled"
    alert_events: list[str] = Field(
        default_factory=lambda: ["kill_switch", "stale_data", "ledger_mismatch", "service_restart"]
    )
    telegram_bot_token_env: str = "STONKS_CLI_CARRY_TELEGRAM_BOT_TOKEN"
    telegram_chat_id_env: str = "STONKS_CLI_CARRY_TELEGRAM_CHAT_ID"
    email_smtp_url_env: str = "STONKS_CLI_CARRY_EMAIL_SMTP_URL"
    email_to_env: str = "STONKS_CLI_CARRY_EMAIL_TO"


class LegalPolicyConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sg_resident: bool = True
    paper_first_venues: list[str] = Field(default_factory=lambda: ["hyperliquid"])
    allowed_spot_fiat_rails: list[str] = Field(
        default_factory=lambda: [
            "anchorage_digital_singapore",
            "bitgo_singapore",
            "bitstamp_asia",
            "blockchain_com_singapore",
            "circle_internet_singapore",
            "coinbase_singapore",
            "dbs_vickers",
            "digital_treasures_center",
        ]
    )
    blocked_venue_ids: list[str] = Field(default_factory=lambda: ["bybit", "kalshi", "polymarket", "sportsbook", "sportsbooks"])
    blocked_strategy_classes: list[str] = Field(
        default_factory=lambda: ["circumvention", "prediction_market", "sportsbook", "sports_betting", "whalemirror_live_target_selection"]
    )


class MoomooConfig(BaseModel):
    """Read-only local OpenD connection settings for the vNext workflow."""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    read_only: Literal[True] = True
    host: str = "127.0.0.1"
    port: int = Field(default=11111, ge=1, le=65535)
    connection_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)
    account_id: str | None = None

    @field_validator("host")
    @classmethod
    def validate_local_opend_host(cls, value: str) -> str:
        host = value.strip().lower()
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("moomoo OpenD host must be local")
        return host

    @field_validator("account_id")
    @classmethod
    def validate_account_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        account_id = value.strip()
        if not account_id:
            raise ValueError("moomoo account_id must be non-empty when configured")
        return account_id

    @property
    def endpoint(self) -> tuple[str, int]:
        return self.host, self.port


class CryptoUniverseConfig(BaseModel):
    """Deterministic crypto research universe; it does not enable execution."""

    model_config = ConfigDict(extra="ignore")
    top_n_by_market_cap: int = Field(default=10, ge=1, le=100)
    include_stablecoins: bool = True
    min_liquidity_usd: float = Field(default=0.0, ge=0.0)


class CryptoMarketCapProviderConfig(BaseModel):
    """Configuration for the read-only USD market-cap provider."""

    model_config = ConfigDict(extra="ignore")
    provider: Literal["coingecko"] = "coingecko"
    api_key_env: str | None = None
    request_timeout_seconds: float = Field(default=5.0, gt=0.0, le=60.0)

    @field_validator("api_key_env")
    @classmethod
    def validate_api_key_env(cls, value: str | None) -> str | None:
        if value is None:
            return None
        environment_variable = value.strip()
        if not environment_variable:
            raise ValueError("crypto market-cap API key environment variable must be non-empty")
        if not re.fullmatch(r"[A-Z_][A-Z0-9_]*", environment_variable):
            raise ValueError("crypto market-cap API key environment variable is invalid")
        return environment_variable


RESEARCH_FACTOR_IDS = ("trend", "momentum", "mean_reversion", "risk_adjusted_performance")
_DEFAULT_RESEARCH_FACTOR_WEIGHTS = {factor_id: 0.25 for factor_id in RESEARCH_FACTOR_IDS}


class FactorWeightsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float] = Field(default_factory=lambda: dict(_DEFAULT_RESEARCH_FACTOR_WEIGHTS))

    @field_validator("weights", mode="before")
    @classmethod
    def validate_weights(cls, value: object) -> dict[str, float]:
        if not isinstance(value, dict) or set(value) != set(RESEARCH_FACTOR_IDS):
            raise ValueError("research factor weights must define every supported factor exactly once")
        if not all(isinstance(factor_id, str) and isinstance(weight, float) and math.isfinite(weight) and weight >= 0 for factor_id, weight in value.items()):
            raise ValueError("research factor weights are invalid")
        return {factor_id: value[factor_id] for factor_id in RESEARCH_FACTOR_IDS}

    @model_validator(mode="after")
    def validate_normalized_weights(self) -> FactorWeightsConfig:
        if not math.isclose(sum(self.weights.values()), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("research factor weights must sum to one")
        return self

    def ordered_items(self) -> tuple[tuple[str, float], ...]:
        return tuple((factor_id, self.weights[factor_id]) for factor_id in RESEARCH_FACTOR_IDS)


class VNextResearchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    crypto_universe: CryptoUniverseConfig = Field(default_factory=CryptoUniverseConfig)
    market_cap_provider: CryptoMarketCapProviderConfig = Field(default_factory=CryptoMarketCapProviderConfig)
    factor_weights: FactorWeightsConfig = Field(default_factory=FactorWeightsConfig)
    cadence: Literal["daily", "weekly"] = "daily"
    llm_summary_enabled: bool = False


class TelegramConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    bot_token_env: str = "STONKS_CLI_TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "STONKS_CLI_TELEGRAM_CHAT_ID"


class VNextOperatorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    broker_app_only: Literal[True] = True
    execution_mode: Literal["disabled"] = "disabled"
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)


class VNextFeatureFlags(BaseModel):
    """Explicit opt-in flags for vNext read-only capabilities."""

    model_config = ConfigDict(extra="forbid")
    broker_data: StrictBool = False
    crypto_research: StrictBool = False
    portfolio: StrictBool = False
    operator_reports: StrictBool = False
    execution: Literal[False] = False


class VNextConfig(BaseModel):
    """Fail-closed configuration for the SG decision-support pivot."""

    model_config = ConfigDict(extra="ignore")
    enabled: bool = False
    moomoo: MoomooConfig = Field(default_factory=MoomooConfig)
    research: VNextResearchConfig = Field(default_factory=VNextResearchConfig)
    operator: VNextOperatorConfig = Field(default_factory=VNextOperatorConfig)
    features: VNextFeatureFlags = Field(default_factory=VNextFeatureFlags)


class TuiConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    refresh_interval: int = Field(default=60, ge=5, le=3600)
    theme: Literal["dark", "light"] = "dark"
    default_view: str = "dashboard"


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")
    schema_version: Literal[2] = CONFIG_SCHEMA_VERSION
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
    whalemirror: WhaleMirrorConfig = Field(default_factory=WhaleMirrorConfig)
    carrymirror: CarryMirrorConfig = Field(default_factory=CarryMirrorConfig)
    legal_policy: LegalPolicyConfig = Field(default_factory=LegalPolicyConfig)
    vnext: VNextConfig = Field(default_factory=VNextConfig)
    tui: TuiConfig = Field(default_factory=TuiConfig)


def config_path() -> Path:
    env = os.getenv("STONKS_CLI_CONFIG")
    return Path(env).expanduser() if env else default_config_path()


def load_config(path: Path | None = None) -> AppConfig:
    path = path or config_path()
    if not path.exists():
        cfg = AppConfig()
    else:
        data = migrate_config_data(json.loads(path.read_text(encoding="utf-8")))
        cfg = AppConfig.model_validate(data)
    validate_config_semantics(cfg)
    return cfg


def save_default_config(path: Path | None = None) -> Path:
    path = path or config_path()
    _write_config(path, AppConfig())
    return path


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    path = path or config_path()
    _write_config(path, cfg)
    return path


def migrate_config_file(path: Path | None = None) -> Path:
    path = path or config_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    migrated = migrate_config_data(data)
    cfg = AppConfig.model_validate(migrated)
    validate_config_semantics(cfg)
    _write_config_data(path, migrated)
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


def migrate_config_data(data: Any) -> dict[str, Any]:
    """Migrate supported on-disk config versions to the current schema."""

    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    migrated = dict(data)
    version = migrated.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("schema_version must be an integer")
    if version == 1:
        migrated["schema_version"] = CONFIG_SCHEMA_VERSION
        return migrated
    if version == CONFIG_SCHEMA_VERSION:
        return migrated
    raise ValueError(f"unsupported future schema_version:{version}")


def validate_config_semantics(cfg: AppConfig) -> None:
    features = cfg.vnext.features
    enabled_features = (
        features.broker_data,
        features.crypto_research,
        features.portfolio,
        features.operator_reports,
    )
    active_services = (
        cfg.vnext.moomoo.enabled,
        cfg.vnext.research.enabled,
        cfg.vnext.operator.telegram.enabled,
    )
    errors: list[str] = []
    if (any(enabled_features) or any(active_services)) and not cfg.vnext.enabled:
        errors.append("vnext.enabled must be true when a vNext capability is enabled")
    if cfg.vnext.moomoo.enabled and not features.broker_data:
        errors.append("vnext.moomoo.enabled requires vnext.features.broker_data")
    if cfg.vnext.research.enabled and not features.crypto_research:
        errors.append("vnext.research.enabled requires vnext.features.crypto_research")
    if cfg.vnext.operator.telegram.enabled and not features.operator_reports:
        errors.append("vnext.operator.telegram.enabled requires vnext.features.operator_reports")
    if errors:
        raise ValueError("invalid config semantics: " + "; ".join(errors))


def redacted_config_data(cfg: AppConfig) -> dict[str, Any]:
    """Return config data safe for terminal and log output."""

    return _redact_value(cfg.model_dump(mode="json"))


def redacted_config_json(cfg: AppConfig, *, indent: int | None = None) -> str:
    return json.dumps(redacted_config_data(cfg), indent=indent, sort_keys=True)


def _write_config(path: Path, cfg: AppConfig) -> None:
    _write_config_data(path, cfg.model_dump(mode="json"))


def _write_config_data(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _redact_value(value: Any, *, key: str = "") -> Any:
    if _is_sensitive_key(key):
        return REDACTED_CONFIG_VALUE if value is not None else None
    if isinstance(value, dict):
        return {str(item_key): _redact_value(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return normalized in {"api_keys", "webhook_url"} or any(marker in normalized for marker in _SENSITIVE_CONFIG_KEY_MARKERS)
