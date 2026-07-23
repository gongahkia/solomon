from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from platformdirs import user_data_path

from stonks_cli.errors import ProfileError, ProviderError
from stonks_cli.types import Currency, DrawdownResponsePolicy

_PROFILE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_ENVIRONMENT_VARIABLE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_BENCHMARK_IDENTIFIER = re.compile(r"^[A-Z][A-Z0-9]{1,9}:[A-Z0-9][A-Z0-9._-]{0,31}$")
_LLM_PROVIDERS = frozenset(("ollama", "openai", "anthropic", "gemini"))
_BUDGET_PERIODS = frozenset(("none", "daily", "monthly"))
_BENCHMARK_RETURN_BASES = frozenset(("price_return", "total_return"))
_STRATEGY_ASSET_CLASSES = frozenset(("individual_equities", "reits", "broad_index_etfs"))


class RiskTolerance(StrEnum):
    CONSERVATIVE = "conservative"
    BALANCED = "balanced"
    GROWTH = "growth"


class StrategyAlgorithm(StrEnum):
    PRICE_TREND = "price_trend"
    RELATIVE_STRENGTH = "relative_strength"
    DIVIDEND_QUALITY = "dividend_quality"


class RelativeStrengthActionMode(StrEnum):
    RANKING_ONLY = "ranking_only"
    INDEPENDENT_BUY_SELL = "independent_buy_sell"


class InsufficientDividendHistoryPolicy(StrEnum):
    ABSTAIN = "abstain"
    LOWER_RANK = "lower_rank"


class StrategyObjective(StrEnum):
    GROWTH = "growth"
    DIVIDEND_INCOME = "dividend_income"
    CAPITAL_PRESERVATION = "capital_preservation"


class DecisionPriority(StrEnum):
    STRATEGY_POLICY = "strategy_policy"
    ALLOCATION_MAINTENANCE = "allocation_maintenance"
    PROFIT_TAKING = "profit_taking"


class DividendReinvestmentPolicy(StrEnum):
    SIGNAL_DIRECTED = "signal_directed_case_by_case"
    REINVEST = "reinvest"
    HOLD_CASH = "hold_cash"


class RebalancePolicy(StrEnum):
    OBSERVE_AND_REVIEW = "observe_and_review"
    MANUAL_ADVISORY = "manual_advisory"


def _strategy_fraction(value: str, field: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be decimal")
    try:
        fraction = Decimal(value)
    except InvalidOperation as error:
        raise ProfileError(f"{field} must be decimal") from error
    if not fraction.is_finite() or not Decimal("0") <= fraction <= Decimal("1"):
        raise ProfileError(f"{field} must be between zero and one")
    return fraction


@dataclass(frozen=True)
class StrategyAllocationTarget:
    asset_class: str
    target_weight: str

    def __post_init__(self) -> None:
        asset_class = self.asset_class.strip().lower() if isinstance(self.asset_class, str) else ""
        if asset_class not in _STRATEGY_ASSET_CLASSES:
            raise ProfileError("strategy allocation asset class is invalid")
        weight = _strategy_fraction(self.target_weight, "strategy allocation target")
        if weight <= 0:
            raise ProfileError("strategy allocation target must be positive")
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "target_weight", format(weight, "f"))

    @property
    def weight(self) -> Decimal:
        return Decimal(self.target_weight)


@dataclass(frozen=True)
class StrategyMarketAllocation:
    asset_class: str
    us_weight: str
    sg_weight: str

    def __post_init__(self) -> None:
        asset_class = self.asset_class.strip().lower() if isinstance(self.asset_class, str) else ""
        if asset_class not in _STRATEGY_ASSET_CLASSES:
            raise ProfileError("strategy market allocation asset class is invalid")
        us_weight = _strategy_fraction(self.us_weight, "strategy US market allocation")
        sg_weight = _strategy_fraction(self.sg_weight, "strategy SG market allocation")
        if us_weight <= 0 or sg_weight <= 0 or us_weight + sg_weight != Decimal("1"):
            raise ProfileError("strategy market allocation weights must be positive and total one")
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "us_weight", format(us_weight, "f"))
        object.__setattr__(self, "sg_weight", format(sg_weight, "f"))


_DEFAULT_STRATEGY_ALLOCATION_TARGETS = (
    StrategyAllocationTarget("individual_equities", "0.50"),
    StrategyAllocationTarget("reits", "0.25"),
    StrategyAllocationTarget("broad_index_etfs", "0.25"),
)
_DEFAULT_STRATEGY_MARKET_ALLOCATIONS = tuple(
    StrategyMarketAllocation(item.asset_class, "0.75", "0.25")
    for item in _DEFAULT_STRATEGY_ALLOCATION_TARGETS
)


def _strategy_enum_tuple(value: object, enum: type[StrEnum], field: str) -> tuple[StrEnum, ...]:
    if not isinstance(value, tuple) or not value:
        raise ProfileError(f"{field} is required")
    try:
        values = tuple(enum(item) for item in value)
    except ValueError as error:
        raise ProfileError(f"{field} is invalid") from error
    if len(set(values)) != len(values):
        raise ProfileError(f"{field} must not contain duplicates")
    return values


@dataclass(frozen=True)
class StrategySettings:
    risk_tolerance: RiskTolerance = RiskTolerance.BALANCED
    risk_tolerance_selected: bool = False
    advisories_enabled: bool = False
    cash_funded_only: bool = True
    long_only: bool = True
    eligible_markets: tuple[str, ...] = ("US", "SG")
    eligible_instrument_types: tuple[str, ...] = (
        "common_equity",
        "non_levered_non_inverse_etf",
        "reit",
    )
    requires_listing: bool = True
    requires_moomoo_cash_eligibility: bool = True
    objective_priority: tuple[StrategyObjective, ...] = (
        StrategyObjective.GROWTH,
        StrategyObjective.DIVIDEND_INCOME,
        StrategyObjective.CAPITAL_PRESERVATION,
    )
    investment_horizon_years: tuple[int, int] = (1, 2)
    allocation_targets: tuple[StrategyAllocationTarget, ...] = _DEFAULT_STRATEGY_ALLOCATION_TARGETS
    market_allocations: tuple[StrategyMarketAllocation, ...] = _DEFAULT_STRATEGY_MARKET_ALLOCATIONS
    enabled_algorithms: tuple[StrategyAlgorithm, ...] = (
        StrategyAlgorithm.PRICE_TREND,
        StrategyAlgorithm.RELATIVE_STRENGTH,
        StrategyAlgorithm.DIVIDEND_QUALITY,
    )
    primary_algorithm: StrategyAlgorithm = StrategyAlgorithm.PRICE_TREND
    relative_strength_action_mode: RelativeStrengthActionMode = (
        RelativeStrengthActionMode.RANKING_ONLY
    )
    relative_strength_lookback_sessions: int = 126
    dividend_reduction_or_omission_downrank: bool = True
    insufficient_dividend_history_policy: InsufficientDividendHistoryPolicy = (
        InsufficientDividendHistoryPolicy.ABSTAIN
    )
    dividend_quality_minimum_observations: int = 3
    trend_exit_consecutive_closes: int = 2
    trend_exit_sma_days: int = 200
    drawdown_threshold: str = "0.25"
    sell_on_risk_breach: bool = True
    rebalance_deviation_threshold: str = "0.05"
    rebalance_policy: RebalancePolicy = RebalancePolicy.OBSERVE_AND_REVIEW
    decision_priority: tuple[DecisionPriority, ...] = (
        DecisionPriority.STRATEGY_POLICY,
        DecisionPriority.ALLOCATION_MAINTENANCE,
        DecisionPriority.PROFIT_TAKING,
    )
    minimum_cash_reserve: str = "0"
    individual_position_limit: str = "0.05"
    broad_etf_position_limit: str = "0.20"
    instrument_restrictions: tuple[str, ...] = ()
    dividend_reinvestment_policy: DividendReinvestmentPolicy = (
        DividendReinvestmentPolicy.SIGNAL_DIRECTED
    )
    version: int = 1

    def __post_init__(self) -> None:
        try:
            risk_tolerance = RiskTolerance(self.risk_tolerance)
            primary_algorithm = StrategyAlgorithm(self.primary_algorithm)
            relative_strength_action_mode = RelativeStrengthActionMode(
                self.relative_strength_action_mode
            )
            insufficient_history_policy = InsufficientDividendHistoryPolicy(
                self.insufficient_dividend_history_policy
            )
            dividend_reinvestment_policy = DividendReinvestmentPolicy(
                self.dividend_reinvestment_policy
            )
            rebalance_policy = RebalancePolicy(self.rebalance_policy)
        except ValueError as error:
            raise ProfileError("strategy setting is invalid") from error
        if not all(
            isinstance(value, bool)
            for value in (
                self.risk_tolerance_selected,
                self.advisories_enabled,
                self.cash_funded_only,
                self.long_only,
                self.requires_listing,
                self.requires_moomoo_cash_eligibility,
            )
        ):
            raise ProfileError("strategy advisory settings must be boolean")
        if self.advisories_enabled and not self.risk_tolerance_selected:
            raise ProfileError(
                "explicit risk tolerance selection is required before enabling advisories"
            )
        if not self.cash_funded_only or not self.long_only:
            raise ProfileError("strategy must remain cash-funded and long-only")
        if self.eligible_markets != ("US", "SG"):
            raise ProfileError("strategy eligible markets must be US and SG")
        if self.eligible_instrument_types != (
            "common_equity",
            "non_levered_non_inverse_etf",
            "reit",
        ):
            raise ProfileError("strategy eligible instruments are fixed")
        if not self.requires_listing or not self.requires_moomoo_cash_eligibility:
            raise ProfileError("strategy eligibility checks must remain required")
        objective_priority = _strategy_enum_tuple(
            self.objective_priority, StrategyObjective, "strategy objective priority"
        )
        if set(objective_priority) != set(StrategyObjective):
            raise ProfileError("strategy objective priority must include every objective once")
        if (
            not isinstance(self.investment_horizon_years, tuple)
            or len(self.investment_horizon_years) != 2
            or any(
                not isinstance(year, int) or isinstance(year, bool)
                for year in self.investment_horizon_years
            )
            or self.investment_horizon_years[0] < 1
            or self.investment_horizon_years[1] < self.investment_horizon_years[0]
            or self.investment_horizon_years[1] > 30
        ):
            raise ProfileError("strategy investment horizon is invalid")
        if not isinstance(self.allocation_targets, tuple) or not all(
            isinstance(item, StrategyAllocationTarget) for item in self.allocation_targets
        ):
            raise ProfileError("strategy allocation targets are invalid")
        target_classes = tuple(item.asset_class for item in self.allocation_targets)
        if set(target_classes) != _STRATEGY_ASSET_CLASSES or len(set(target_classes)) != len(
            target_classes
        ):
            raise ProfileError(
                "strategy allocation targets must cover the configured asset classes once"
            )
        if sum((item.weight for item in self.allocation_targets), Decimal("0")) != Decimal("1"):
            raise ProfileError("strategy allocation targets must total one")
        if not isinstance(self.market_allocations, tuple) or not all(
            isinstance(item, StrategyMarketAllocation) for item in self.market_allocations
        ):
            raise ProfileError("strategy market allocations are invalid")
        market_classes = tuple(item.asset_class for item in self.market_allocations)
        if set(market_classes) != _STRATEGY_ASSET_CLASSES or len(set(market_classes)) != len(
            market_classes
        ):
            raise ProfileError(
                "strategy market allocations must cover the configured asset classes once"
            )
        enabled_algorithms = _strategy_enum_tuple(
            self.enabled_algorithms, StrategyAlgorithm, "strategy algorithms"
        )
        if primary_algorithm not in enabled_algorithms:
            raise ProfileError("strategy primary algorithm must be enabled")
        if (
            not isinstance(self.relative_strength_lookback_sessions, int)
            or isinstance(self.relative_strength_lookback_sessions, bool)
            or not 2 <= self.relative_strength_lookback_sessions <= 1_260
        ):
            raise ProfileError(
                "strategy relative strength lookback must be between 2 and 1260 sessions"
            )
        if (
            not isinstance(self.dividend_quality_minimum_observations, int)
            or isinstance(self.dividend_quality_minimum_observations, bool)
            or not 2 <= self.dividend_quality_minimum_observations <= 100
        ):
            raise ProfileError("strategy dividend history minimum must be between 2 and 100")
        if not isinstance(self.dividend_reduction_or_omission_downrank, bool) or not isinstance(
            self.sell_on_risk_breach, bool
        ):
            raise ProfileError("strategy policy settings must be boolean")
        if (
            not isinstance(self.trend_exit_consecutive_closes, int)
            or isinstance(self.trend_exit_consecutive_closes, bool)
            or not 1 <= self.trend_exit_consecutive_closes <= 30
        ):
            raise ProfileError("strategy trend exit closes must be between 1 and 30")
        if (
            not isinstance(self.trend_exit_sma_days, int)
            or isinstance(self.trend_exit_sma_days, bool)
            or not 2 <= self.trend_exit_sma_days <= 1_000
        ):
            raise ProfileError("strategy trend exit SMA days must be between 2 and 1000")
        drawdown_threshold = _strategy_fraction(
            self.drawdown_threshold, "strategy drawdown threshold"
        )
        rebalance_deviation_threshold = _strategy_fraction(
            self.rebalance_deviation_threshold, "strategy rebalance deviation threshold"
        )
        minimum_cash_reserve = _strategy_fraction(
            self.minimum_cash_reserve, "strategy minimum cash reserve"
        )
        individual_position_limit = _strategy_fraction(
            self.individual_position_limit, "strategy individual position limit"
        )
        broad_etf_position_limit = _strategy_fraction(
            self.broad_etf_position_limit, "strategy broad ETF position limit"
        )
        if drawdown_threshold <= 0 or rebalance_deviation_threshold <= 0:
            raise ProfileError("strategy drawdown and rebalance thresholds must be positive")
        if individual_position_limit <= 0 or broad_etf_position_limit <= 0:
            raise ProfileError("strategy position limits must be positive")
        if broad_etf_position_limit < individual_position_limit:
            raise ProfileError(
                "strategy broad ETF position limit must not be below individual limit"
            )
        decision_priority = _strategy_enum_tuple(
            self.decision_priority, DecisionPriority, "strategy decision priority"
        )
        if set(decision_priority) != set(DecisionPriority):
            raise ProfileError("strategy decision priority must include every priority once")
        if not isinstance(self.instrument_restrictions, tuple) or not all(
            isinstance(item, str) and 0 < len(item.strip()) <= 128
            for item in self.instrument_restrictions
        ):
            raise ProfileError("strategy instrument restrictions are invalid")
        restrictions = tuple(item.strip().upper() for item in self.instrument_restrictions)
        if len(set(restrictions)) != len(restrictions):
            raise ProfileError("strategy instrument restrictions must not contain duplicates")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("strategy settings version must be a positive integer")
        object.__setattr__(self, "risk_tolerance", risk_tolerance)
        object.__setattr__(
            self, "objective_priority", cast(tuple[StrategyObjective, ...], objective_priority)
        )
        object.__setattr__(
            self, "enabled_algorithms", cast(tuple[StrategyAlgorithm, ...], enabled_algorithms)
        )
        object.__setattr__(self, "primary_algorithm", primary_algorithm)
        object.__setattr__(self, "relative_strength_action_mode", relative_strength_action_mode)
        object.__setattr__(
            self, "insufficient_dividend_history_policy", insufficient_history_policy
        )
        object.__setattr__(self, "rebalance_policy", rebalance_policy)
        object.__setattr__(self, "drawdown_threshold", format(drawdown_threshold, "f"))
        object.__setattr__(
            self, "rebalance_deviation_threshold", format(rebalance_deviation_threshold, "f")
        )
        object.__setattr__(
            self, "decision_priority", cast(tuple[DecisionPriority, ...], decision_priority)
        )
        object.__setattr__(self, "minimum_cash_reserve", format(minimum_cash_reserve, "f"))
        object.__setattr__(
            self, "individual_position_limit", format(individual_position_limit, "f")
        )
        object.__setattr__(self, "broad_etf_position_limit", format(broad_etf_position_limit, "f"))
        object.__setattr__(self, "instrument_restrictions", restrictions)
        object.__setattr__(self, "dividend_reinvestment_policy", dividend_reinvestment_policy)

    @property
    def effective_risk_breach_action(self) -> str:
        if not self.advisories_enabled:
            return "advisories_disabled"
        if self.sell_on_risk_breach and self.risk_tolerance is not RiskTolerance.GROWTH:
            return "manual_sell_advisory"
        return "alert_only"


def canonical_benchmark_identifier(identifier: str) -> str:
    value = identifier.strip().upper() if isinstance(identifier, str) else ""
    if not _BENCHMARK_IDENTIFIER.fullmatch(value):
        raise ProfileError("benchmark identifier must be canonical MARKET:SYMBOL")
    return value


@dataclass(frozen=True)
class DividendSettings:
    allow_explicit_credit: bool = False
    allow_currency_conversion: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.allow_explicit_credit, bool):
            raise ProfileError("dividend explicit credit setting must be boolean")
        if not isinstance(self.allow_currency_conversion, bool):
            raise ProfileError("dividend currency conversion setting must be boolean")
        if self.allow_currency_conversion and not self.allow_explicit_credit:
            raise ProfileError("dividend currency conversion requires explicit credit")


@dataclass(frozen=True)
class DrawdownSettings:
    warning_threshold: str = "0.25"
    response_policy: DrawdownResponsePolicy = DrawdownResponsePolicy.ALERT_ONLY
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.warning_threshold, str) or not self.warning_threshold.strip():
            raise ProfileError("drawdown warning threshold must be decimal")
        try:
            threshold = Decimal(self.warning_threshold)
        except InvalidOperation as error:
            raise ProfileError("drawdown warning threshold must be decimal") from error
        if not threshold.is_finite() or not Decimal("0") < threshold < Decimal("1"):
            raise ProfileError("drawdown warning threshold must be between zero and one")
        try:
            policy = DrawdownResponsePolicy(self.response_policy)
        except ValueError as error:
            raise ProfileError("drawdown response policy is invalid") from error
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("drawdown settings version must be a positive integer")
        object.__setattr__(self, "warning_threshold", format(threshold, "f"))
        object.__setattr__(self, "response_policy", policy)

    @property
    def threshold(self) -> Decimal:
        return Decimal(self.warning_threshold)


@dataclass(frozen=True)
class FxReportingSettings:
    maximum_age_calendar_days: int = 3
    version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_age_calendar_days, int)
            or isinstance(self.maximum_age_calendar_days, bool)
            or not 0 <= self.maximum_age_calendar_days <= 365
        ):
            raise ProfileError("FX maximum age must be between 0 and 365 calendar days")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("FX reporting settings version must be a positive integer")


@dataclass(frozen=True)
class JournalSettings:
    open_on_advisory: bool = True
    retention_days: int | None = None
    display_reasons: bool = False
    version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.open_on_advisory, bool) or not isinstance(
            self.display_reasons, bool
        ):
            raise ProfileError("journal settings flags must be boolean")
        if self.retention_days is not None and (
            not isinstance(self.retention_days, int)
            or isinstance(self.retention_days, bool)
            or not 1 <= self.retention_days <= 36_500
        ):
            raise ProfileError("journal retention days must be between 1 and 36500")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("journal settings version must be a positive integer")


@dataclass(frozen=True)
class EODUniverseSettings:
    individual_price_floor_usd: str = "5"
    liquidity_floor_sgd: str = "500000"
    liquidity_window_sessions: int = 20
    liquidity_minimum_sessions: int = 15
    maximum_spread_fraction: str = "0.01"
    version: int = 1

    def __post_init__(self) -> None:
        try:
            price_floor = Decimal(self.individual_price_floor_usd)
            liquidity_floor = Decimal(self.liquidity_floor_sgd)
            spread = Decimal(self.maximum_spread_fraction)
        except InvalidOperation as error:
            raise ProfileError("universe thresholds must be decimal") from error
        if not price_floor.is_finite() or price_floor <= 0:
            raise ProfileError("universe individual price floor must be positive")
        if not liquidity_floor.is_finite() or liquidity_floor <= 0:
            raise ProfileError("universe liquidity floor must be positive")
        if not spread.is_finite() or not Decimal("0") < spread <= Decimal("1"):
            raise ProfileError("universe maximum spread must be between zero and one")
        if (
            not isinstance(self.liquidity_window_sessions, int)
            or isinstance(self.liquidity_window_sessions, bool)
            or self.liquidity_window_sessions < 1
        ):
            raise ProfileError("universe liquidity window must be a positive integer")
        if (
            not isinstance(self.liquidity_minimum_sessions, int)
            or isinstance(self.liquidity_minimum_sessions, bool)
            or not 1 <= self.liquidity_minimum_sessions <= self.liquidity_window_sessions
        ):
            raise ProfileError("universe liquidity minimum sessions is invalid")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("universe settings version must be positive")
        object.__setattr__(self, "individual_price_floor_usd", format(price_floor, "f"))
        object.__setattr__(self, "liquidity_floor_sgd", format(liquidity_floor, "f"))
        object.__setattr__(self, "maximum_spread_fraction", format(spread, "f"))


@dataclass(frozen=True)
class BenchmarkComponent:
    identifier: str
    name: str
    currency: Currency
    weight: str
    source_url: str
    return_basis: str = "total_return"

    def __post_init__(self) -> None:
        identifier = canonical_benchmark_identifier(self.identifier)
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name.strip()) > 256:
            raise ProfileError("benchmark name is invalid")
        if not isinstance(self.currency, Currency):
            raise ProfileError("benchmark currency is invalid")
        if not isinstance(self.weight, str) or not self.weight.strip():
            raise ProfileError("benchmark weight must be decimal")
        try:
            weight = Decimal(self.weight)
        except InvalidOperation as error:
            raise ProfileError("benchmark weight must be decimal") from error
        if not weight.is_finite() or not Decimal("0") < weight <= Decimal("1"):
            raise ProfileError("benchmark weight must be between zero and one")
        if not isinstance(self.source_url, str):
            raise ProfileError("benchmark source URL is invalid")
        source_url = self.source_url.strip()
        parsed = urlsplit(source_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ProfileError("benchmark source URL must be an HTTPS URL without credentials")
        return_basis = (
            self.return_basis.strip().lower() if isinstance(self.return_basis, str) else ""
        )
        if return_basis not in _BENCHMARK_RETURN_BASES:
            raise ProfileError("benchmark return basis is invalid")
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "weight", format(weight, "f"))
        object.__setattr__(self, "source_url", source_url)
        object.__setattr__(self, "return_basis", return_basis)

    @property
    def decimal_weight(self) -> Decimal:
        return Decimal(self.weight)


_DEFAULT_BENCHMARK_COMPONENTS = (
    BenchmarkComponent(
        "US:SPX",
        "S&P 500 Index",
        Currency.USD,
        "0.75",
        "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
    ),
    BenchmarkComponent(
        "SG:STI",
        "Straits Times Index",
        Currency.SGD,
        "0.25",
        "https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/straits-times-index-ground-rules.pdf",
    ),
)


@dataclass(frozen=True)
class BenchmarkSettings:
    components: tuple[BenchmarkComponent, ...] = _DEFAULT_BENCHMARK_COMPONENTS
    version: int = 1

    def __post_init__(self) -> None:
        if not self.components or not all(
            isinstance(item, BenchmarkComponent) for item in self.components
        ):
            raise ProfileError("benchmark components are required")
        identifiers = tuple(item.identifier for item in self.components)
        if len(set(identifiers)) != len(identifiers):
            raise ProfileError("benchmark components must be unique")
        if sum((item.decimal_weight for item in self.components), Decimal("0")) != Decimal("1"):
            raise ProfileError("benchmark component weights must total one")
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ProfileError("benchmark settings version must be a positive integer")


@dataclass(frozen=True)
class LLMSettings:
    provider: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_local_only: bool = False
    budget_period: str = "none"
    budget_limit_sgd: str | None = None
    input_cost_per_million_sgd: str = "0"
    output_cost_per_million_sgd: str = "0"
    max_output_tokens: int = 600
    allow_cloud: bool = False

    def __post_init__(self) -> None:
        if self.provider is None:
            if self.model is not None or self.api_key_env is not None:
                raise ProfileError("LLM model and key environment require a provider")
            return
        provider = self.provider.strip().lower()
        if provider not in _LLM_PROVIDERS:
            raise ProfileError("LLM provider is invalid")
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 256:
            raise ProfileError("LLM model is required")
        if self.api_key_env is not None and not _ENVIRONMENT_VARIABLE.fullmatch(self.api_key_env):
            raise ProfileError("LLM key environment variable is invalid")
        if self.budget_period not in _BUDGET_PERIODS:
            raise ProfileError("LLM budget period is invalid")
        if not isinstance(self.max_output_tokens, int) or not 1 <= self.max_output_tokens <= 4096:
            raise ProfileError("LLM max output tokens must be between 1 and 4096")
        try:
            from decimal import Decimal

            input_cost = Decimal(self.input_cost_per_million_sgd)
            output_cost = Decimal(self.output_cost_per_million_sgd)
            limit = None if self.budget_limit_sgd is None else Decimal(self.budget_limit_sgd)
        except Exception as error:
            raise ProfileError("LLM budget values must be decimal") from error
        if input_cost < 0 or output_cost < 0 or (limit is not None and limit <= 0):
            raise ProfileError("LLM budget values must be positive")
        if self.budget_period == "none" and limit is not None:
            raise ProfileError("LLM budget limit requires a daily or monthly period")
        if self.budget_period != "none" and limit is None:
            raise ProfileError("LLM budget period requires a limit")
        if provider != "ollama" and not self.allow_cloud:
            raise ProfileError("cloud LLM provider requires explicit privacy acknowledgement")
        if provider == "ollama" and not self.ollama_local_only:
            raise ProfileError("Ollama requires explicit local-only acknowledgement")
        parsed = urlsplit(self.ollama_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ProfileError("Ollama URL must be a loopback HTTP endpoint")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", self.model.strip())

    @property
    def enabled(self) -> bool:
        return self.provider is not None


def app_root() -> Path:
    override = __import__("os").environ.get("STONKS_CLI_HOME")
    return (
        Path(override).expanduser().resolve()
        if override
        else user_data_path("stonks-cli", appauthor=False)
    )


def validate_profile_name(name: str) -> str:
    if not _PROFILE.fullmatch(name):
        raise ProfileError("profile must match [a-z][a-z0-9_-]{0,63}")
    return name


@dataclass(frozen=True)
class ProfileConfig:
    name: str
    key_file: str
    providers: tuple[str, ...] = ("csv", "moomoo")
    benchmarks: tuple[str, ...] = ()
    schema_version: int = 1
    llm: LLMSettings = LLMSettings()
    dividends: DividendSettings = DividendSettings()
    reporting_currency: Currency = Currency.SGD
    drawdown: DrawdownSettings = DrawdownSettings()
    fx_reporting: FxReportingSettings = FxReportingSettings()
    journal: JournalSettings = JournalSettings()
    benchmark: BenchmarkSettings = BenchmarkSettings()
    universe: EODUniverseSettings = EODUniverseSettings()
    strategy: StrategySettings = StrategySettings()

    def __post_init__(self) -> None:
        validate_profile_name(self.name)
        if not Path(self.key_file).is_absolute():
            raise ProfileError("key_file must be absolute")
        try:
            from stonks_cli.plugins import validate_provider_configuration

            providers = validate_provider_configuration(self.providers)
        except ProviderError as error:
            raise ProfileError(str(error)) from error
        if not isinstance(self.reporting_currency, Currency):
            raise ProfileError("profile reporting currency is invalid")
        if not isinstance(self.benchmark, BenchmarkSettings):
            raise ProfileError("profile benchmark settings are invalid")
        if not isinstance(self.drawdown, DrawdownSettings):
            raise ProfileError("profile drawdown settings are invalid")
        if not isinstance(self.fx_reporting, FxReportingSettings):
            raise ProfileError("profile FX reporting settings are invalid")
        if not isinstance(self.journal, JournalSettings):
            raise ProfileError("profile journal settings are invalid")
        if not isinstance(self.universe, EODUniverseSettings):
            raise ProfileError("profile universe settings are invalid")
        if not isinstance(self.strategy, StrategySettings):
            raise ProfileError("profile strategy settings are invalid")
        object.__setattr__(self, "providers", providers)


def profile_dir(name: str) -> Path:
    return app_root() / "profiles" / validate_profile_name(name)


def config_path(name: str) -> Path:
    return profile_dir(name) / "profile.json"


def save_profile(config: ProfileConfig) -> None:
    directory = profile_dir(config.name)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    path = config_path(config.name)
    data = asdict(config)
    if not config.llm.enabled:
        data.pop("llm")
    if config.dividends == DividendSettings():
        data.pop("dividends")
    if config.reporting_currency is Currency.SGD:
        data.pop("reporting_currency")
    data["benchmark"] = {
        "components": [
            {
                "identifier": component.identifier,
                "name": component.name,
                "currency": component.currency.value,
                "weight": component.weight,
                "source_url": component.source_url,
                "return_basis": component.return_basis,
            }
            for component in config.benchmark.components
        ],
        "version": config.benchmark.version,
    }
    data["strategy"] = strategy_settings_to_data(config.strategy)
    if config.drawdown == DrawdownSettings():
        data.pop("drawdown")
    if config.fx_reporting == FxReportingSettings():
        data.pop("fx_reporting")
    if config.journal == JournalSettings():
        data.pop("journal")
    if config.universe == EODUniverseSettings():
        data.pop("universe")
    if config.strategy == StrategySettings():
        data.pop("strategy")
    payload = json.dumps(data, sort_keys=True, indent=2).encode() + b"\n"
    path.write_bytes(payload)
    path.chmod(0o600)


def enable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    providers = (*config.providers, provider_id)
    return replace(config, providers=providers)


def disable_provider(config: ProfileConfig, provider_id: str) -> ProfileConfig:
    identifier = provider_id.strip().lower()
    providers = tuple(item for item in config.providers if item != identifier)
    if len(providers) == len(config.providers):
        raise ProfileError("provider is not enabled")
    return replace(config, providers=providers)


def configure_drawdown(
    config: ProfileConfig, warning_threshold: str, response_policy: DrawdownResponsePolicy | str
) -> ProfileConfig:
    try:
        policy = DrawdownResponsePolicy(response_policy)
    except ValueError as error:
        raise ProfileError("drawdown response policy is invalid") from error
    candidate = DrawdownSettings(warning_threshold, policy, config.drawdown.version)
    if candidate == config.drawdown:
        return config
    return replace(config, drawdown=replace(candidate, version=config.drawdown.version + 1))


def configure_fx_reporting(config: ProfileConfig, maximum_age_calendar_days: int) -> ProfileConfig:
    candidate = FxReportingSettings(maximum_age_calendar_days, config.fx_reporting.version)
    if candidate == config.fx_reporting:
        return config
    return replace(
        config,
        fx_reporting=replace(candidate, version=config.fx_reporting.version + 1),
    )


def configure_benchmark(
    config: ProfileConfig, components: tuple[BenchmarkComponent, ...]
) -> ProfileConfig:
    candidate = BenchmarkSettings(components, config.benchmark.version)
    if candidate == config.benchmark:
        return config
    return replace(config, benchmark=replace(candidate, version=config.benchmark.version + 1))


def configure_journal(
    config: ProfileConfig,
    *,
    open_on_advisory: bool,
    retention_days: int | None,
    display_reasons: bool,
) -> ProfileConfig:
    candidate = JournalSettings(
        open_on_advisory,
        retention_days,
        display_reasons,
        config.journal.version,
    )
    if candidate == config.journal:
        return config
    return replace(config, journal=replace(candidate, version=config.journal.version + 1))


def configure_universe(
    config: ProfileConfig,
    *,
    individual_price_floor_usd: str,
    liquidity_floor_sgd: str,
    liquidity_window_sessions: int,
    liquidity_minimum_sessions: int,
    maximum_spread_fraction: str,
) -> ProfileConfig:
    candidate = EODUniverseSettings(
        individual_price_floor_usd,
        liquidity_floor_sgd,
        liquidity_window_sessions,
        liquidity_minimum_sessions,
        maximum_spread_fraction,
        config.universe.version,
    )
    if candidate == config.universe:
        return config
    return replace(config, universe=replace(candidate, version=config.universe.version + 1))


def configure_strategy(config: ProfileConfig, settings: StrategySettings) -> ProfileConfig:
    if not isinstance(settings, StrategySettings):
        raise ProfileError("strategy settings are invalid")
    candidate = replace(settings, version=config.strategy.version)
    if candidate == config.strategy:
        return config
    return replace(config, strategy=replace(candidate, version=config.strategy.version + 1))


def benchmark_settings_from_data(value: object) -> BenchmarkSettings:
    if value is None:
        return BenchmarkSettings()
    if not isinstance(value, dict):
        raise TypeError("benchmark must be an object")
    if "components" not in value:
        return BenchmarkSettings()
    component_values = value["components"]
    if not isinstance(component_values, list):
        raise TypeError("benchmark components must be a list")
    return BenchmarkSettings(
        tuple(
            BenchmarkComponent(
                identifier=item["identifier"],
                name=item["name"],
                currency=Currency(item["currency"]),
                weight=item["weight"],
                source_url=item["source_url"],
                return_basis=item.get("return_basis", "total_return"),
            )
            for item in component_values
        ),
        int(value.get("version", 1)),
    )


def strategy_settings_to_data(settings: StrategySettings) -> dict[str, object]:
    if not isinstance(settings, StrategySettings):
        raise TypeError("strategy settings are invalid")
    return {
        "risk_tolerance": settings.risk_tolerance.value,
        "risk_tolerance_selected": settings.risk_tolerance_selected,
        "advisories_enabled": settings.advisories_enabled,
        "cash_funded_only": settings.cash_funded_only,
        "long_only": settings.long_only,
        "eligible_markets": list(settings.eligible_markets),
        "eligible_instrument_types": list(settings.eligible_instrument_types),
        "requires_listing": settings.requires_listing,
        "requires_moomoo_cash_eligibility": settings.requires_moomoo_cash_eligibility,
        "objective_priority": [item.value for item in settings.objective_priority],
        "investment_horizon_years": list(settings.investment_horizon_years),
        "allocation_targets": [
            {"asset_class": item.asset_class, "target_weight": item.target_weight}
            for item in settings.allocation_targets
        ],
        "market_allocations": [
            {
                "asset_class": item.asset_class,
                "us_weight": item.us_weight,
                "sg_weight": item.sg_weight,
            }
            for item in settings.market_allocations
        ],
        "enabled_algorithms": [item.value for item in settings.enabled_algorithms],
        "primary_algorithm": settings.primary_algorithm.value,
        "relative_strength_action_mode": settings.relative_strength_action_mode.value,
        "relative_strength_lookback_sessions": settings.relative_strength_lookback_sessions,
        "dividend_reduction_or_omission_downrank": (
            settings.dividend_reduction_or_omission_downrank
        ),
        "insufficient_dividend_history_policy": settings.insufficient_dividend_history_policy.value,
        "dividend_quality_minimum_observations": settings.dividend_quality_minimum_observations,
        "trend_exit_consecutive_closes": settings.trend_exit_consecutive_closes,
        "trend_exit_sma_days": settings.trend_exit_sma_days,
        "drawdown_threshold": settings.drawdown_threshold,
        "sell_on_risk_breach": settings.sell_on_risk_breach,
        "rebalance_deviation_threshold": settings.rebalance_deviation_threshold,
        "rebalance_policy": settings.rebalance_policy.value,
        "decision_priority": [item.value for item in settings.decision_priority],
        "minimum_cash_reserve": settings.minimum_cash_reserve,
        "individual_position_limit": settings.individual_position_limit,
        "broad_etf_position_limit": settings.broad_etf_position_limit,
        "instrument_restrictions": list(settings.instrument_restrictions),
        "dividend_reinvestment_policy": settings.dividend_reinvestment_policy.value,
        "version": settings.version,
    }


def strategy_settings_from_data(value: object) -> StrategySettings:
    if value is None:
        return StrategySettings()
    if not isinstance(value, dict):
        raise TypeError("strategy must be an object")
    allocation_targets = value.get("allocation_targets", _DEFAULT_STRATEGY_ALLOCATION_TARGETS)
    market_allocations = value.get("market_allocations", _DEFAULT_STRATEGY_MARKET_ALLOCATIONS)
    if not isinstance(allocation_targets, (list, tuple)) or not isinstance(
        market_allocations, (list, tuple)
    ):
        raise TypeError("strategy allocations must be lists")
    return StrategySettings(
        risk_tolerance=RiskTolerance(value.get("risk_tolerance", RiskTolerance.BALANCED)),
        risk_tolerance_selected=value.get("risk_tolerance_selected", False),
        advisories_enabled=value.get("advisories_enabled", False),
        cash_funded_only=value.get("cash_funded_only", True),
        long_only=value.get("long_only", True),
        eligible_markets=tuple(value.get("eligible_markets", ("US", "SG"))),
        eligible_instrument_types=tuple(
            value.get(
                "eligible_instrument_types",
                ("common_equity", "non_levered_non_inverse_etf", "reit"),
            )
        ),
        requires_listing=value.get("requires_listing", True),
        requires_moomoo_cash_eligibility=value.get("requires_moomoo_cash_eligibility", True),
        objective_priority=tuple(value.get("objective_priority", tuple(StrategyObjective))),
        investment_horizon_years=tuple(value.get("investment_horizon_years", (1, 2))),
        allocation_targets=tuple(
            item
            if isinstance(item, StrategyAllocationTarget)
            else StrategyAllocationTarget(item["asset_class"], item["target_weight"])
            for item in allocation_targets
        ),
        market_allocations=tuple(
            item
            if isinstance(item, StrategyMarketAllocation)
            else StrategyMarketAllocation(item["asset_class"], item["us_weight"], item["sg_weight"])
            for item in market_allocations
        ),
        enabled_algorithms=tuple(value.get("enabled_algorithms", tuple(StrategyAlgorithm))),
        primary_algorithm=StrategyAlgorithm(
            value.get("primary_algorithm", StrategyAlgorithm.PRICE_TREND)
        ),
        relative_strength_action_mode=RelativeStrengthActionMode(
            value.get("relative_strength_action_mode", RelativeStrengthActionMode.RANKING_ONLY)
        ),
        relative_strength_lookback_sessions=value.get("relative_strength_lookback_sessions", 126),
        dividend_reduction_or_omission_downrank=value.get(
            "dividend_reduction_or_omission_downrank", True
        ),
        insufficient_dividend_history_policy=InsufficientDividendHistoryPolicy(
            value.get(
                "insufficient_dividend_history_policy",
                InsufficientDividendHistoryPolicy.ABSTAIN,
            )
        ),
        dividend_quality_minimum_observations=value.get("dividend_quality_minimum_observations", 3),
        trend_exit_consecutive_closes=value.get("trend_exit_consecutive_closes", 2),
        trend_exit_sma_days=value.get("trend_exit_sma_days", 200),
        drawdown_threshold=value.get("drawdown_threshold", "0.25"),
        sell_on_risk_breach=value.get("sell_on_risk_breach", True),
        rebalance_deviation_threshold=value.get("rebalance_deviation_threshold", "0.05"),
        rebalance_policy=RebalancePolicy(
            value.get("rebalance_policy", RebalancePolicy.OBSERVE_AND_REVIEW)
        ),
        decision_priority=tuple(value.get("decision_priority", tuple(DecisionPriority))),
        minimum_cash_reserve=value.get("minimum_cash_reserve", "0"),
        individual_position_limit=value.get("individual_position_limit", "0.05"),
        broad_etf_position_limit=value.get("broad_etf_position_limit", "0.20"),
        instrument_restrictions=tuple(value.get("instrument_restrictions", ())),
        dividend_reinvestment_policy=DividendReinvestmentPolicy(
            value.get("dividend_reinvestment_policy", DividendReinvestmentPolicy.SIGNAL_DIRECTED)
        ),
        version=value.get("version", 1),
    )


def load_profile(name: str) -> ProfileConfig:
    path = config_path(name)
    if not path.is_file():
        raise ProfileError("profile not found")
    try:
        value = json.loads(path.read_text())
        benchmark = benchmark_settings_from_data(value.get("benchmark"))
        return ProfileConfig(
            name=value["name"],
            key_file=value["key_file"],
            providers=tuple(value.get("providers", ("csv", "moomoo"))),
            benchmarks=tuple(value.get("benchmarks", ())),
            benchmark=benchmark,
            schema_version=int(value.get("schema_version", 1)),
            llm=LLMSettings(**value.get("llm", {})),
            dividends=DividendSettings(**value.get("dividends", {})),
            reporting_currency=Currency(value.get("reporting_currency", Currency.SGD)),
            drawdown=DrawdownSettings(**value.get("drawdown", {})),
            fx_reporting=FxReportingSettings(**value.get("fx_reporting", {})),
            journal=JournalSettings(**value.get("journal", {})),
            universe=EODUniverseSettings(**value.get("universe", {})),
            strategy=strategy_settings_from_data(value.get("strategy")),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ProfileError("invalid profile") from error
