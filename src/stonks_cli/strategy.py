from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast
from uuid import uuid4

from stonks_cli.config import (
    InsufficientDividendHistoryPolicy,
    JournalSettings,
    RelativeStrengthActionMode,
    StrategyAlgorithm,
    StrategySettings,
    strategy_settings_from_data,
    strategy_settings_to_data,
)
from stonks_cli.errors import ProviderError
from stonks_cli.ledger import list_events
from stonks_cli.market_data import DailyPrice
from stonks_cli.storage import EncryptedLedger
from stonks_cli.types import (
    AssetClass,
    Currency,
    EventKind,
    EventLifecycle,
    InstrumentMaster,
    ListingStatus,
)


@dataclass(frozen=True)
class DailyBar:
    close: Decimal
    signal: bool
    split_ratio: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ValueError("daily close must be positive")
        if self.split_ratio <= 0:
            raise ValueError("split ratio must be positive")


@dataclass(frozen=True)
class BacktestResult:
    total_return: Decimal
    periods: int
    trade_count: int
    strategy_values: tuple[Decimal, ...]


@dataclass(frozen=True)
class StrategyRunCard:
    strategy_name: str
    universe: str
    signal_definition: str
    fee_rate: Decimal
    slippage_rate: Decimal
    source_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.strategy_name,
                self.universe,
                self.signal_definition,
                self.source_hash,
            )
        ):
            raise ValueError("strategy run card fields are required")
        if len(self.source_hash) != 64:
            raise ValueError("strategy source hash must be a SHA-256 digest")
        if self.fee_rate < 0 or self.slippage_rate < 0:
            raise ValueError("strategy costs must be non-negative")
        if self.created_at.tzinfo is None:
            raise ValueError("strategy run card time must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


@dataclass(frozen=True)
class StrategyArtifact:
    artifact_id: str
    run_card: StrategyRunCard
    result: BacktestResult
    benchmark_return: Decimal


@dataclass(frozen=True)
class StrategyJournalEntry:
    entry_id: str
    created_at: datetime
    summary: str
    rationale: str

    def __post_init__(self) -> None:
        if not self.entry_id.strip() or not self.summary.strip() or not self.rationale.strip():
            raise ValueError("strategy journal fields are required")
        if self.created_at.tzinfo is None:
            raise ValueError("strategy journal time must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))


class AdvisoryJournalDisposition(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_EXECUTED = "partially_executed"
    DEFERRED = "deferred"
    EXPIRED = "expired"


@dataclass(frozen=True)
class AdvisoryJournalDispositionRecord:
    recorded_at: datetime
    disposition: AdvisoryJournalDisposition
    reason: str | None

    def __post_init__(self) -> None:
        if self.recorded_at.tzinfo is None:
            raise ValueError("journal disposition time must be timezone-aware")
        if not isinstance(self.disposition, AdvisoryJournalDisposition):
            raise ValueError("journal disposition is invalid")
        reason = _optional_journal_text(self.reason)
        object.__setattr__(self, "recorded_at", self.recorded_at.astimezone(UTC))
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class AdvisoryJournalEntry:
    entry_id: str
    advisory_id: str
    profile: str
    configuration_version: str
    opened_at: datetime
    updated_at: datetime
    disposition: AdvisoryJournalDisposition | None
    disposition_at: datetime | None
    reason: str | None
    evidence_fingerprints: tuple[str, ...]
    disposition_history: tuple[AdvisoryJournalDispositionRecord, ...]

    def __post_init__(self) -> None:
        values = (self.entry_id, self.advisory_id, self.profile, self.configuration_version)
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError("journal identity fields are required")
        if self.opened_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("journal times must be timezone-aware")
        opened_at = self.opened_at.astimezone(UTC)
        updated_at = self.updated_at.astimezone(UTC)
        if updated_at < opened_at:
            raise ValueError("journal update time must not precede opening")
        reason = _optional_journal_text(self.reason)
        if self.disposition is None:
            if self.disposition_at is not None or reason is not None or self.disposition_history:
                raise ValueError("undisposed journal entries cannot include a disposition")
        else:
            if (
                not isinstance(self.disposition, AdvisoryJournalDisposition)
                or self.disposition_at is None
            ):
                raise ValueError("journal disposition timestamp is required")
            if self.disposition_at.tzinfo is None:
                raise ValueError("journal disposition time must be timezone-aware")
            disposition_at = self.disposition_at.astimezone(UTC)
            if (
                disposition_at < opened_at
                or disposition_at > updated_at
                or not self.disposition_history
            ):
                raise ValueError("journal disposition history is invalid")
            if self.disposition_history[-1].disposition is not self.disposition:
                raise ValueError("journal disposition must match its history")
            object.__setattr__(self, "disposition_at", disposition_at)
        if (
            not isinstance(self.evidence_fingerprints, tuple)
            or not all(
                isinstance(value, str) and value.strip() for value in self.evidence_fingerprints
            )
            or len(set(self.evidence_fingerprints)) != len(self.evidence_fingerprints)
        ):
            raise ValueError("journal evidence fingerprints are invalid")
        object.__setattr__(self, "entry_id", self.entry_id.strip())
        object.__setattr__(self, "advisory_id", self.advisory_id.strip())
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "configuration_version", self.configuration_version.strip())
        object.__setattr__(self, "opened_at", opened_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "reason", reason)


@dataclass(frozen=True)
class JournalSettingsAuditRecord:
    profile: str
    changed_at: datetime
    settings: JournalSettings

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("journal settings profile is required")
        if self.changed_at.tzinfo is None or not isinstance(self.settings, JournalSettings):
            raise ValueError("journal settings audit record is invalid")
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "changed_at", self.changed_at.astimezone(UTC))


@dataclass(frozen=True)
class StrategySettingsAuditRecord:
    profile: str
    changed_at: datetime
    settings: StrategySettings

    def __post_init__(self) -> None:
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("strategy settings profile is required")
        if self.changed_at.tzinfo is None or not isinstance(self.settings, StrategySettings):
            raise ValueError("strategy settings audit record is invalid")
        object.__setattr__(self, "profile", self.profile.strip())
        object.__setattr__(self, "changed_at", self.changed_at.astimezone(UTC))


class SignalAction(StrEnum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    ABSTAIN = "abstain"


class SignalConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNAVAILABLE = "unavailable"
    CONFLICTED = "conflicted"


class SignalStatus(StrEnum):
    AVAILABLE = "available"
    INSUFFICIENT_HISTORY = "insufficient_history"
    INSUFFICIENT_COMPARABLE_INSTRUMENTS = "insufficient_comparable_instruments"
    INSUFFICIENT_HISTORY_DOWNRANKED = "insufficient_history_downranked"
    DOWNRANKED = "downranked"
    UNSUPPORTED_INSTRUMENT = "unsupported_instrument"
    CONFLICT = "conflict"


_SIGNAL_SUPPORTED_ASSET_CLASSES = (AssetClass.EQUITY, AssetClass.ETF, AssetClass.REIT)
_SIGNAL_SUPPORTED_MARKETS = ("US", "SG")


@dataclass(frozen=True)
class DividendObservation:
    observation_date: date
    amount_per_share: Decimal
    currency: Currency
    source_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation_date, date) or not isinstance(self.currency, Currency):
            raise ValueError("dividend observation date and currency are required")
        if self.amount_per_share <= 0:
            raise ValueError("dividend observation amount must be positive")
        object.__setattr__(self, "amount_per_share", Decimal(self.amount_per_share))
        object.__setattr__(self, "source_hash", _signal_source_hash(self.source_hash))


@dataclass(frozen=True)
class StrategySignalInput:
    instrument: InstrumentMaster
    daily_prices: tuple[DailyPrice, ...]
    dividend_observations: tuple[DividendObservation, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, InstrumentMaster):
            raise ValueError("strategy signal instrument is required")
        if not isinstance(self.daily_prices, tuple) or not self.daily_prices:
            raise ValueError("strategy signal daily prices are required")
        if not all(isinstance(item, DailyPrice) for item in self.daily_prices):
            raise ValueError("strategy signal daily prices are invalid")
        if any(item.instrument.key != self.instrument.canonical_id for item in self.daily_prices):
            raise ValueError("strategy signal daily prices must match the instrument")
        dates = tuple(item.session_date for item in self.daily_prices)
        if dates != tuple(sorted(dates)) or len(set(dates)) != len(dates):
            raise ValueError("strategy signal daily prices must be ordered and unique")
        if not isinstance(self.dividend_observations, tuple) or not all(
            isinstance(item, DividendObservation) for item in self.dividend_observations
        ):
            raise ValueError("strategy dividend observations are invalid")
        dividend_dates = tuple(item.observation_date for item in self.dividend_observations)
        if dividend_dates != tuple(sorted(dividend_dates)) or len(set(dividend_dates)) != len(
            dividend_dates
        ):
            raise ValueError("strategy dividend observations must be ordered and unique")
        if len({item.currency for item in self.dividend_observations}) > 1:
            raise ValueError("strategy dividend observations require one currency")

    @property
    def input_hash(self) -> str:
        return _signal_hash(_strategy_signal_input_data(self))


@dataclass(frozen=True)
class StrategyAlgorithmDeclaration:
    algorithm: StrategyAlgorithm
    version: int
    required_inputs: tuple[str, ...]
    parameters: tuple[tuple[str, str], ...]
    supported_asset_classes: tuple[AssetClass, ...] = _SIGNAL_SUPPORTED_ASSET_CLASSES
    supported_markets: tuple[str, ...] = _SIGNAL_SUPPORTED_MARKETS

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, StrategyAlgorithm) or self.version < 1:
            raise ValueError("strategy algorithm declaration is invalid")
        if not self.required_inputs or not all(
            isinstance(item, str) and item for item in self.required_inputs
        ):
            raise ValueError("strategy algorithm required inputs are invalid")
        if not all(
            isinstance(item, tuple)
            and len(item) == 2
            and all(isinstance(value, str) and value for value in item)
            for item in self.parameters
        ):
            raise ValueError("strategy algorithm parameters are invalid")
        if not self.supported_asset_classes or not all(
            isinstance(item, AssetClass) for item in self.supported_asset_classes
        ):
            raise ValueError("strategy algorithm asset classes are invalid")
        if self.supported_markets != _SIGNAL_SUPPORTED_MARKETS:
            raise ValueError("strategy algorithm markets are invalid")


@dataclass(frozen=True)
class AlgorithmSignal:
    instrument_key: str
    declaration: StrategyAlgorithmDeclaration
    action: SignalAction
    score: Decimal | None
    confidence: SignalConfidence
    status: SignalStatus
    rationale: tuple[str, ...]
    input_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.instrument_key, str) or not self.instrument_key.strip():
            raise ValueError("strategy signal instrument is required")
        if not isinstance(self.declaration, StrategyAlgorithmDeclaration):
            raise ValueError("strategy signal declaration is required")
        if not isinstance(self.action, SignalAction) or not isinstance(
            self.confidence, SignalConfidence
        ):
            raise ValueError("strategy signal action and confidence are required")
        if not isinstance(self.status, SignalStatus):
            raise ValueError("strategy signal status is required")
        if self.score is not None and not self.score.is_finite():
            raise ValueError("strategy signal score must be finite")
        if not self.rationale or not all(isinstance(item, str) and item for item in self.rationale):
            raise ValueError("strategy signal rationale is required")
        object.__setattr__(self, "instrument_key", self.instrument_key.strip().upper())
        if self.score is not None:
            object.__setattr__(self, "score", Decimal(self.score))
        object.__setattr__(self, "input_hash", _signal_source_hash(self.input_hash))


@dataclass(frozen=True)
class InstrumentSignalSummary:
    instrument_key: str
    primary_signal: AlgorithmSignal
    policy_signals: tuple[AlgorithmSignal, ...]
    conflict: bool
    displayed_confidence: SignalConfidence

    def __post_init__(self) -> None:
        if not isinstance(self.primary_signal, AlgorithmSignal):
            raise ValueError("strategy primary signal is required")
        if not isinstance(self.policy_signals, tuple) or not self.policy_signals:
            raise ValueError("strategy policy signals are required")
        if any(
            item.instrument_key != self.primary_signal.instrument_key
            for item in self.policy_signals
        ):
            raise ValueError("strategy policy signals must match the primary signal")
        if not isinstance(self.conflict, bool) or not isinstance(
            self.displayed_confidence, SignalConfidence
        ):
            raise ValueError("strategy summary is invalid")
        if self.conflict != (self.displayed_confidence is SignalConfidence.CONFLICTED):
            raise ValueError("strategy conflict confidence is invalid")
        object.__setattr__(self, "instrument_key", self.primary_signal.instrument_key)


@dataclass(frozen=True)
class StrategySignalArtifact:
    configuration_version: int
    input_hash: str
    summaries: tuple[InstrumentSignalSummary, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.configuration_version, int) or self.configuration_version < 1:
            raise ValueError("strategy signal configuration version is invalid")
        if not isinstance(self.summaries, tuple) or not self.summaries:
            raise ValueError("strategy signal summaries are required")
        keys = tuple(item.instrument_key for item in self.summaries)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("strategy signal summaries must be ordered and unique")
        object.__setattr__(self, "input_hash", _signal_source_hash(self.input_hash))


def run_daily_bar_signals(
    inputs: Sequence[StrategySignalInput], settings: StrategySettings
) -> StrategySignalArtifact:
    if not isinstance(settings, StrategySettings):
        raise ValueError("strategy settings are required")
    if not inputs or not all(isinstance(item, StrategySignalInput) for item in inputs):
        raise ValueError("strategy signal inputs are required")
    ordered_inputs = tuple(sorted(inputs, key=lambda item: item.instrument.canonical_id))
    keys = tuple(item.instrument.canonical_id for item in ordered_inputs)
    if len(set(keys)) != len(keys):
        raise ValueError("strategy signal inputs must be unique")
    signals: dict[str, list[AlgorithmSignal]] = {
        item.instrument.canonical_id: [] for item in ordered_inputs
    }
    for item in ordered_inputs:
        if StrategyAlgorithm.PRICE_TREND in settings.enabled_algorithms:
            signals[item.instrument.canonical_id].append(_price_trend_signal(item, settings))
        if StrategyAlgorithm.DIVIDEND_QUALITY in settings.enabled_algorithms:
            signals[item.instrument.canonical_id].append(_dividend_quality_signal(item, settings))
    if StrategyAlgorithm.RELATIVE_STRENGTH in settings.enabled_algorithms:
        for signal in _relative_strength_signals(ordered_inputs, settings):
            signals[signal.instrument_key].append(signal)
    summaries = tuple(
        _signal_summary(
            item.instrument.canonical_id, tuple(signals[item.instrument.canonical_id]), settings
        )
        for item in ordered_inputs
    )
    return StrategySignalArtifact(
        settings.version,
        _signal_hash(
            {
                "settings": strategy_settings_to_data(settings),
                "inputs": [_strategy_signal_input_data(item) for item in ordered_inputs],
            }
        ),
        summaries,
    )


def _signal_summary(
    instrument_key: str, signals: tuple[AlgorithmSignal, ...], settings: StrategySettings
) -> InstrumentSignalSummary:
    by_algorithm = {item.declaration.algorithm: item for item in signals}
    primary = by_algorithm[settings.primary_algorithm]
    comparable_actions = {
        item.action
        for item in signals
        if _participates_in_conflict(item, settings)
        and item.status is SignalStatus.AVAILABLE
        and item.action is not SignalAction.ABSTAIN
    }
    conflict = len(comparable_actions) > 1
    return InstrumentSignalSummary(
        instrument_key,
        primary,
        tuple(sorted(signals, key=lambda item: item.declaration.algorithm.value)),
        conflict,
        SignalConfidence.CONFLICTED if conflict else primary.confidence,
    )


def _participates_in_conflict(signal: AlgorithmSignal, settings: StrategySettings) -> bool:
    if signal.declaration.algorithm is StrategyAlgorithm.PRICE_TREND:
        return True
    return (
        signal.declaration.algorithm is StrategyAlgorithm.RELATIVE_STRENGTH
        and settings.relative_strength_action_mode
        is RelativeStrengthActionMode.INDEPENDENT_BUY_SELL
    )


def _price_trend_signal(
    input_value: StrategySignalInput, settings: StrategySettings
) -> AlgorithmSignal:
    declaration = _algorithm_declaration(StrategyAlgorithm.PRICE_TREND, settings)
    if not _signal_supported(input_value):
        return _unsupported_signal(input_value, declaration)
    required_history = settings.trend_exit_sma_days + settings.trend_exit_consecutive_closes - 1
    if len(input_value.daily_prices) < required_history:
        return _unavailable_signal(
            input_value,
            declaration,
            SignalStatus.INSUFFICIENT_HISTORY,
            f"requires {required_history} completed daily closes",
        )
    closes = tuple(item.close for item in input_value.daily_prices)
    below_sma = all(
        closes[end - 1]
        < sum(closes[end - settings.trend_exit_sma_days : end], Decimal("0"))
        / settings.trend_exit_sma_days
        for end in range(
            len(closes) - settings.trend_exit_consecutive_closes + 1,
            len(closes) + 1,
        )
    )
    latest_sma = (
        sum(closes[-settings.trend_exit_sma_days :], Decimal("0")) / settings.trend_exit_sma_days
    )
    score = closes[-1] / latest_sma - Decimal("1")
    if below_sma:
        return AlgorithmSignal(
            input_value.instrument.canonical_id,
            declaration,
            SignalAction.SELL,
            score,
            SignalConfidence.HIGH,
            SignalStatus.AVAILABLE,
            (
                f"{settings.trend_exit_consecutive_closes} completed closes are below the "
                f"{settings.trend_exit_sma_days}-session SMA",
                "profit alone is not an exit condition",
            ),
            input_value.input_hash,
        )
    if closes[-1] > latest_sma:
        return AlgorithmSignal(
            input_value.instrument.canonical_id,
            declaration,
            SignalAction.BUY,
            score,
            SignalConfidence.MEDIUM,
            SignalStatus.AVAILABLE,
            (f"latest completed close is above the {settings.trend_exit_sma_days}-session SMA",),
            input_value.input_hash,
        )
    return AlgorithmSignal(
        input_value.instrument.canonical_id,
        declaration,
        SignalAction.HOLD,
        score,
        SignalConfidence.LOW,
        SignalStatus.AVAILABLE,
        (
            "latest completed close is not above the SMA",
            "trend exit remains inactive until the configured completed-close count is met",
        ),
        input_value.input_hash,
    )


def _relative_strength_signals(
    inputs: tuple[StrategySignalInput, ...], settings: StrategySettings
) -> tuple[AlgorithmSignal, ...]:
    declaration = _algorithm_declaration(StrategyAlgorithm.RELATIVE_STRENGTH, settings)
    values: dict[str, Decimal] = {}
    groups: dict[tuple[AssetClass, str], list[StrategySignalInput]] = {}
    output: dict[str, AlgorithmSignal] = {}
    for item in inputs:
        if not _signal_supported(item):
            output[item.instrument.canonical_id] = _unsupported_signal(item, declaration)
            continue
        if len(item.daily_prices) <= settings.relative_strength_lookback_sessions:
            output[item.instrument.canonical_id] = _unavailable_signal(
                item,
                declaration,
                SignalStatus.INSUFFICIENT_HISTORY,
                f"requires {settings.relative_strength_lookback_sessions + 1} completed daily closes",
            )
            continue
        values[item.instrument.canonical_id] = item.daily_prices[-1].close / item.daily_prices[
            -settings.relative_strength_lookback_sessions - 1
        ].close - Decimal("1")
        groups.setdefault((item.instrument.asset_class, item.instrument.market), []).append(item)
    for group in groups.values():
        eligible = tuple(item for item in group if item.instrument.canonical_id in values)
        if len(eligible) < 2:
            for item in eligible:
                output[item.instrument.canonical_id] = _unavailable_signal(
                    item,
                    declaration,
                    SignalStatus.INSUFFICIENT_COMPARABLE_INSTRUMENTS,
                    "requires at least two comparable eligible instruments",
                )
            continue
        ranked = tuple(
            sorted(
                eligible,
                key=lambda item: (
                    -values[item.instrument.canonical_id],
                    item.instrument.canonical_id,
                ),
            )
        )
        best = values[ranked[0].instrument.canonical_id]
        worst = values[ranked[-1].instrument.canonical_id]
        for index, item in enumerate(ranked, start=1):
            score = values[item.instrument.canonical_id]
            if settings.relative_strength_action_mode is RelativeStrengthActionMode.RANKING_ONLY:
                action = SignalAction.HOLD
            elif best == worst:
                action = SignalAction.HOLD
            elif score == best:
                action = SignalAction.BUY
            elif score == worst:
                action = SignalAction.SELL
            else:
                action = SignalAction.HOLD
            output[item.instrument.canonical_id] = AlgorithmSignal(
                item.instrument.canonical_id,
                declaration,
                action,
                score,
                SignalConfidence.MEDIUM if len(ranked) >= 3 else SignalConfidence.LOW,
                SignalStatus.AVAILABLE,
                (
                    f"rank {index} of {len(ranked)} by {settings.relative_strength_lookback_sessions}-session return",
                    f"action mode is {settings.relative_strength_action_mode.value}",
                ),
                item.input_hash,
            )
    return tuple(output[item.instrument.canonical_id] for item in inputs)


def _dividend_quality_signal(
    input_value: StrategySignalInput, settings: StrategySettings
) -> AlgorithmSignal:
    declaration = _algorithm_declaration(StrategyAlgorithm.DIVIDEND_QUALITY, settings)
    if not _signal_supported(input_value):
        return _unsupported_signal(input_value, declaration)
    observations = input_value.dividend_observations
    if len(observations) < settings.dividend_quality_minimum_observations:
        if (
            settings.insufficient_dividend_history_policy
            is InsufficientDividendHistoryPolicy.ABSTAIN
        ):
            return _unavailable_signal(
                input_value,
                declaration,
                SignalStatus.INSUFFICIENT_HISTORY,
                f"requires {settings.dividend_quality_minimum_observations} sourced distributions",
            )
        return AlgorithmSignal(
            input_value.instrument.canonical_id,
            declaration,
            SignalAction.HOLD,
            Decimal("-1"),
            SignalConfidence.LOW,
            SignalStatus.INSUFFICIENT_HISTORY_DOWNRANKED,
            (
                f"fewer than {settings.dividend_quality_minimum_observations} sourced distributions",
                "insufficient history is configured to lower rank",
                "dividend quality does not create available cash",
            ),
            input_value.input_hash,
        )
    prior_amount = _decimal_median(tuple(item.amount_per_share for item in observations[:-1]))
    latest_amount = observations[-1].amount_per_share
    intervals = tuple(
        (right.observation_date - left.observation_date).days
        for left, right in zip(observations, observations[1:], strict=True)
    )
    expected_interval = _integer_median(intervals)
    omitted = input_value.daily_prices[-1].session_date >= observations[
        -1
    ].observation_date + timedelta(days=expected_interval * 2)
    reduced = latest_amount < prior_amount
    downranked = settings.dividend_reduction_or_omission_downrank and (reduced or omitted)
    rationale = ["dividend quality is ranking-only and does not create available cash"]
    if reduced:
        rationale.append("latest sourced distribution is below the historical median")
    if omitted:
        rationale.append("distribution timing is beyond twice the sourced median interval")
    if not reduced and not omitted:
        rationale.append("latest sourced distribution is not reduced against the historical median")
    return AlgorithmSignal(
        input_value.instrument.canonical_id,
        declaration,
        SignalAction.HOLD,
        Decimal("0") if omitted else latest_amount / prior_amount - Decimal("1"),
        SignalConfidence.LOW if downranked else SignalConfidence.MEDIUM,
        SignalStatus.DOWNRANKED if downranked else SignalStatus.AVAILABLE,
        tuple(rationale),
        input_value.input_hash,
    )


def _algorithm_declaration(
    algorithm: StrategyAlgorithm, settings: StrategySettings
) -> StrategyAlgorithmDeclaration:
    if algorithm is StrategyAlgorithm.PRICE_TREND:
        return StrategyAlgorithmDeclaration(
            algorithm,
            1,
            ("completed_daily_closes",),
            (
                ("sma_days", str(settings.trend_exit_sma_days)),
                ("consecutive_closes", str(settings.trend_exit_consecutive_closes)),
            ),
        )
    if algorithm is StrategyAlgorithm.RELATIVE_STRENGTH:
        return StrategyAlgorithmDeclaration(
            algorithm,
            1,
            ("completed_daily_closes", "comparable_eligible_instruments"),
            (
                ("lookback_sessions", str(settings.relative_strength_lookback_sessions)),
                ("action_mode", settings.relative_strength_action_mode.value),
            ),
        )
    return StrategyAlgorithmDeclaration(
        algorithm,
        1,
        ("sourced_distribution_history", "completed_daily_closes"),
        (
            ("minimum_observations", str(settings.dividend_quality_minimum_observations)),
            ("insufficient_history_policy", settings.insufficient_dividend_history_policy.value),
            (
                "reduction_or_omission_downrank",
                str(settings.dividend_reduction_or_omission_downrank).lower(),
            ),
        ),
    )


def _unavailable_signal(
    input_value: StrategySignalInput,
    declaration: StrategyAlgorithmDeclaration,
    status: SignalStatus,
    reason: str,
) -> AlgorithmSignal:
    return AlgorithmSignal(
        input_value.instrument.canonical_id,
        declaration,
        SignalAction.ABSTAIN,
        None,
        SignalConfidence.UNAVAILABLE,
        status,
        (reason,),
        input_value.input_hash,
    )


def _unsupported_signal(
    input_value: StrategySignalInput, declaration: StrategyAlgorithmDeclaration
) -> AlgorithmSignal:
    return _unavailable_signal(
        input_value,
        declaration,
        SignalStatus.UNSUPPORTED_INSTRUMENT,
        "instrument is unlisted, restricted, or outside supported asset classes or markets",
    )


def _signal_supported(input_value: StrategySignalInput) -> bool:
    return (
        input_value.instrument.asset_class in _SIGNAL_SUPPORTED_ASSET_CLASSES
        and input_value.instrument.market in _SIGNAL_SUPPORTED_MARKETS
        and input_value.instrument.listing_status is ListingStatus.LISTED
        and not any(
            (
                input_value.instrument.margin_only,
                input_value.instrument.short_only,
                input_value.instrument.leveraged,
                input_value.instrument.inverse,
            )
        )
    )


def _strategy_signal_input_data(input_value: StrategySignalInput) -> dict[str, object]:
    return {
        "instrument": {
            "canonical_id": input_value.instrument.canonical_id,
            "asset_class": input_value.instrument.asset_class.value,
            "market": input_value.instrument.market,
            "metadata_version": input_value.instrument.metadata_version,
            "metadata_source_hash": input_value.instrument.metadata_source_hash,
            "classification_version": input_value.instrument.classification_version,
            "sector_version": input_value.instrument.sector_version,
            "sector_source_hash": input_value.instrument.sector_source_hash,
        },
        "daily_prices": [
            {
                "session_date": item.session_date.isoformat(),
                "close": str(item.close),
                "source_hash": _signal_source_hash(item.source_hash),
            }
            for item in input_value.daily_prices
        ],
        "dividend_observations": [
            {
                "observation_date": item.observation_date.isoformat(),
                "amount_per_share": str(item.amount_per_share),
                "currency": item.currency.value,
                "source_hash": item.source_hash,
            }
            for item in input_value.dividend_observations
        ],
    }


def _signal_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _signal_source_hash(value: str) -> str:
    normalized = value.lower() if isinstance(value, str) else ""
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("strategy signal source hash must be a SHA-256 digest")
    return normalized


def _decimal_median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def _integer_median(values: tuple[int, ...]) -> int:
    ordered = tuple(sorted(values))
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) // 2


def simulate_eod_long_only(
    bars: Sequence[DailyBar], *, fee_rate: Decimal, slippage_rate: Decimal
) -> BacktestResult:
    if fee_rate < 0 or slippage_rate < 0:
        raise ValueError("fee and slippage rates must be non-negative")
    if len(bars) < 2:
        raise ValueError("at least two daily bars are required")
    value = Decimal("1")
    values = [value]
    trades = 0
    invested = False
    for index in range(1, len(bars)):
        should_hold = bars[index - 1].signal  # signal is known only after the prior close
        if should_hold != invested:
            value *= Decimal("1") - fee_rate - slippage_rate
            trades += 1
            invested = should_hold
        if invested:
            value *= bars[index].close * bars[index].split_ratio / bars[index - 1].close
        values.append(value)
    return BacktestResult(value - Decimal("1"), len(bars) - 1, trades, tuple(values))


def buy_and_hold_return(bars: Sequence[DailyBar]) -> Decimal:
    if len(bars) < 2:
        raise ValueError("at least two daily bars are required")
    value = Decimal("1")
    for index in range(1, len(bars)):
        value *= bars[index].close * bars[index].split_ratio / bars[index - 1].close
    return value - Decimal("1")


def run_csv_backtest(
    ledger: EncryptedLedger, path: Path, *, fee_rate: Decimal, slippage_rate: Decimal
) -> tuple[BacktestResult, str]:
    content = path.read_bytes()
    source_hash = ledger.archive_source(content)
    try:
        rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise ProviderError("strategy CSV must be UTF-8") from error
    if rows.fieldnames is None or not {"close", "signal"} <= set(rows.fieldnames):
        raise ProviderError("strategy CSV requires close and signal columns")
    bars: list[DailyBar] = []
    for row in rows:
        signal = (row["signal"] or "").strip().lower()
        if signal not in {"0", "1", "false", "true"}:
            raise ProviderError("strategy signal must be true/false or 1/0")
        bars.append(
            DailyBar(
                Decimal(row["close"] or ""),
                signal in {"1", "true"},
                Decimal(row.get("split_ratio") or "1"),
            )
        )
    return simulate_eod_long_only(bars, fee_rate=fee_rate, slippage_rate=slippage_rate), source_hash


def store_artifact(
    ledger: EncryptedLedger,
    run_card: StrategyRunCard,
    result: BacktestResult,
    benchmark_return: Decimal,
) -> StrategyArtifact:
    artifact = StrategyArtifact(uuid4().hex, run_card, result, Decimal(benchmark_return))
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT INTO strategy_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                run_card.strategy_name,
                run_card.universe,
                run_card.signal_definition,
                str(run_card.fee_rate),
                str(run_card.slippage_rate),
                run_card.source_hash,
                run_card.created_at.isoformat(),
                str(result.total_return),
                str(benchmark_return),
                result.trade_count,
            ),
        )
    return artifact


def list_artifacts(ledger: EncryptedLedger) -> tuple[StrategyArtifact, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM strategy_artifacts ORDER BY created_at, artifact_id"
        ).fetchall()
    return tuple(
        StrategyArtifact(
            row["artifact_id"],
            StrategyRunCard(
                row["strategy_name"],
                row["universe"],
                row["signal_definition"],
                Decimal(row["fee_rate"]),
                Decimal(row["slippage_rate"]),
                row["source_hash"],
                datetime.fromisoformat(row["created_at"]),
            ),
            BacktestResult(Decimal(row["total_return"]), 0, int(row["trade_count"]), ()),
            Decimal(row["benchmark_return"]),
        )
        for row in rows
    )


def append_journal_entry(
    ledger: EncryptedLedger, summary: str, rationale: str, *, created_at: datetime | None = None
) -> StrategyJournalEntry:
    entry = StrategyJournalEntry(uuid4().hex, created_at or datetime.now(UTC), summary, rationale)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO strategy_journal VALUES (?, ?, ?, ?)",
            (entry.entry_id, entry.created_at.isoformat(), entry.summary, entry.rationale),
        )
    return entry


def list_journal_entries(ledger: EncryptedLedger) -> tuple[StrategyJournalEntry, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM strategy_journal ORDER BY created_at, entry_id"
        ).fetchall()
    return tuple(
        StrategyJournalEntry(
            row["entry_id"],
            datetime.fromisoformat(row["created_at"]),
            row["summary"],
            row["rationale"],
        )
        for row in rows
    )


def open_advisory_journal(
    ledger: EncryptedLedger,
    advisory_id: str,
    configuration_version: str,
    settings: JournalSettings,
    *,
    opened_at: datetime | None = None,
) -> AdvisoryJournalEntry | None:
    if not isinstance(settings, JournalSettings):
        raise ValueError("journal settings are required")
    if not settings.open_on_advisory:
        return None
    now = _journal_time(opened_at)
    purge_expired_advisory_journal_entries(ledger, settings.retention_days, now=now)
    with ledger.connection() as connection:
        _initialize(connection)
        existing = connection.execute(
            """
            SELECT * FROM advisory_journal_entries
            WHERE advisory_id = ? AND profile = ? AND configuration_version = ?
            ORDER BY opened_at, entry_id LIMIT 1
            """,
            (advisory_id, ledger.config.name, configuration_version),
        ).fetchone()
        if existing is not None:
            return _advisory_journal_entry_from_row(connection, existing)
    entry = AdvisoryJournalEntry(
        uuid4().hex,
        advisory_id,
        ledger.config.name,
        configuration_version,
        now,
        now,
        None,
        None,
        None,
        (),
        (),
    )
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            """
            INSERT INTO advisory_journal_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.entry_id,
                entry.advisory_id,
                entry.profile,
                entry.configuration_version,
                entry.opened_at.isoformat(),
                entry.updated_at.isoformat(),
                None,
                None,
                None,
            ),
        )
    return entry


def advisory_journal_entry(ledger: EncryptedLedger, entry_id: str) -> AdvisoryJournalEntry | None:
    with ledger.connection() as connection:
        _initialize(connection)
        row = connection.execute(
            "SELECT * FROM advisory_journal_entries WHERE entry_id = ? AND profile = ?",
            (entry_id, ledger.config.name),
        ).fetchone()
        return None if row is None else _advisory_journal_entry_from_row(connection, row)


def record_advisory_journal_disposition(
    ledger: EncryptedLedger,
    entry_id: str,
    disposition: AdvisoryJournalDisposition | str,
    *,
    reason: str | None = None,
    recorded_at: datetime | None = None,
) -> AdvisoryJournalEntry:
    try:
        selected = AdvisoryJournalDisposition(disposition)
    except ValueError as error:
        raise ValueError("journal disposition is invalid") from error
    now = _journal_time(recorded_at)
    normalized_reason = _optional_journal_text(reason)
    with ledger.connection() as connection:
        _initialize(connection)
        row = _advisory_journal_row(connection, ledger, entry_id)
        entry = _advisory_journal_entry_from_row(connection, row)
        if now < entry.updated_at:
            raise ValueError("journal disposition time must not precede the latest entry update")
        connection.execute(
            "INSERT INTO advisory_journal_dispositions VALUES (?, ?, ?, ?, ?)",
            (uuid4().hex, entry.entry_id, now.isoformat(), selected.value, normalized_reason),
        )
        connection.execute(
            """
            UPDATE advisory_journal_entries
            SET updated_at = ?, disposition = ?, disposition_at = ?, reason = ?
            WHERE entry_id = ?
            """,
            (now.isoformat(), selected.value, now.isoformat(), normalized_reason, entry.entry_id),
        )
        updated = _advisory_journal_row(connection, ledger, entry.entry_id)
        return _advisory_journal_entry_from_row(connection, updated)


def link_advisory_journal_evidence(
    ledger: EncryptedLedger,
    entry_id: str,
    event_fingerprint: str,
    *,
    linked_at: datetime | None = None,
) -> AdvisoryJournalEntry:
    normalized_fingerprint = event_fingerprint.strip() if isinstance(event_fingerprint, str) else ""
    if not normalized_fingerprint:
        raise ValueError("journal evidence fingerprint is required")
    event = next(
        (item for item in list_events(ledger) if item.fingerprint == normalized_fingerprint), None
    )
    if (
        event is None
        or event.lifecycle is not EventLifecycle.POSTED
        or event.kind not in {EventKind.BUY, EventKind.SELL}
    ):
        raise ValueError("journal evidence must be an imported posted buy or sell event")
    now = _journal_time(linked_at)
    with ledger.connection() as connection:
        _initialize(connection)
        row = _advisory_journal_row(connection, ledger, entry_id)
        entry = _advisory_journal_entry_from_row(connection, row)
        if entry.disposition not in {
            AdvisoryJournalDisposition.ACCEPTED,
            AdvisoryJournalDisposition.PARTIALLY_EXECUTED,
        }:
            raise ValueError(
                "journal evidence requires an accepted or partially executed disposition"
            )
        if now < entry.updated_at:
            raise ValueError("journal evidence time must not precede the latest entry update")
        inserted = connection.execute(
            "INSERT OR IGNORE INTO advisory_journal_evidence VALUES (?, ?, ?)",
            (entry.entry_id, normalized_fingerprint, now.isoformat()),
        ).rowcount
        if inserted == 1:
            connection.execute(
                "UPDATE advisory_journal_entries SET updated_at = ? WHERE entry_id = ?",
                (now.isoformat(), entry.entry_id),
            )
        updated = _advisory_journal_row(connection, ledger, entry.entry_id)
        return _advisory_journal_entry_from_row(connection, updated)


def list_advisory_journal_entries(
    ledger: EncryptedLedger, *, retention_days: int | None = None, now: datetime | None = None
) -> tuple[AdvisoryJournalEntry, ...]:
    purge_expired_advisory_journal_entries(ledger, retention_days, now=now)
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT * FROM advisory_journal_entries WHERE profile = ? ORDER BY opened_at, entry_id",
            (ledger.config.name,),
        ).fetchall()
        return tuple(_advisory_journal_entry_from_row(connection, row) for row in rows)


def purge_expired_advisory_journal_entries(
    ledger: EncryptedLedger, retention_days: int | None, *, now: datetime | None = None
) -> int:
    if retention_days is None:
        return 0
    if (
        not isinstance(retention_days, int)
        or isinstance(retention_days, bool)
        or retention_days < 1
    ):
        raise ValueError("journal retention days must be positive")
    cutoff = _journal_time(now) - timedelta(days=retention_days)
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            "SELECT entry_id FROM advisory_journal_entries WHERE profile = ? AND opened_at < ?",
            (ledger.config.name, cutoff.isoformat()),
        ).fetchall()
        entry_ids = tuple(row["entry_id"] for row in rows)
        if not entry_ids:
            return 0
        placeholders = ", ".join("?" for _ in entry_ids)
        connection.execute(
            f"DELETE FROM advisory_journal_dispositions WHERE entry_id IN ({placeholders})",
            entry_ids,
        )
        connection.execute(
            f"DELETE FROM advisory_journal_evidence WHERE entry_id IN ({placeholders})", entry_ids
        )
        connection.execute(
            f"DELETE FROM advisory_journal_entries WHERE entry_id IN ({placeholders})", entry_ids
        )
    return len(entry_ids)


def record_journal_settings_audit(
    ledger: EncryptedLedger, settings: JournalSettings, *, changed_at: datetime | None = None
) -> JournalSettingsAuditRecord:
    record = JournalSettingsAuditRecord(ledger.config.name, _journal_time(changed_at), settings)
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO advisory_journal_settings_audit VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.profile,
                record.changed_at.isoformat(),
                settings.open_on_advisory,
                settings.retention_days,
                settings.display_reasons,
                settings.version,
            ),
        )
    return record


def journal_settings_audit(ledger: EncryptedLedger) -> tuple[JournalSettingsAuditRecord, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM advisory_journal_settings_audit
            WHERE profile = ? ORDER BY changed_at, configuration_version
            """,
            (ledger.config.name,),
        ).fetchall()
    return tuple(
        JournalSettingsAuditRecord(
            row["profile"],
            datetime.fromisoformat(row["changed_at"]),
            JournalSettings(
                bool(row["open_on_advisory"]),
                None if row["retention_days"] is None else int(row["retention_days"]),
                bool(row["display_reasons"]),
                int(row["configuration_version"]),
            ),
        )
        for row in rows
    )


def record_strategy_settings_audit(
    ledger: EncryptedLedger, settings: StrategySettings, *, changed_at: datetime | None = None
) -> StrategySettingsAuditRecord:
    record = StrategySettingsAuditRecord(ledger.config.name, _journal_time(changed_at), settings)
    payload = json.dumps(strategy_settings_to_data(settings), sort_keys=True, separators=(",", ":"))
    with ledger.connection() as connection:
        _initialize(connection)
        connection.execute(
            "INSERT INTO strategy_settings_audit VALUES (?, ?, ?, ?)",
            (record.profile, record.changed_at.isoformat(), settings.version, payload),
        )
    return record


def strategy_settings_audit(ledger: EncryptedLedger) -> tuple[StrategySettingsAuditRecord, ...]:
    with ledger.connection() as connection:
        _initialize(connection)
        rows = connection.execute(
            """
            SELECT * FROM strategy_settings_audit
            WHERE profile = ? ORDER BY changed_at, configuration_version
            """,
            (ledger.config.name,),
        ).fetchall()
    try:
        return tuple(
            StrategySettingsAuditRecord(
                row["profile"],
                datetime.fromisoformat(row["changed_at"]),
                strategy_settings_from_data(json.loads(row["settings_json"])),
            )
            for row in rows
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("strategy settings audit is invalid") from error


def _optional_journal_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > 4_096:
        raise ValueError("journal reason is invalid")
    return value.strip() or None


def _journal_time(value: datetime | None) -> datetime:
    now = datetime.now(UTC) if value is None else value
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("journal time must be timezone-aware")
    return now.astimezone(UTC)


def _advisory_journal_row(
    connection: sqlite3.Connection, ledger: EncryptedLedger, entry_id: str
) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM advisory_journal_entries WHERE entry_id = ? AND profile = ?",
        (entry_id, ledger.config.name),
    ).fetchone()
    if row is None:
        raise ValueError("journal entry was not found")
    return cast(sqlite3.Row, row)


def _advisory_journal_entry_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> AdvisoryJournalEntry:
    evidence = tuple(
        item["event_fingerprint"]
        for item in connection.execute(
            "SELECT event_fingerprint FROM advisory_journal_evidence WHERE entry_id = ? ORDER BY linked_at, event_fingerprint",
            (row["entry_id"],),
        ).fetchall()
    )
    history = tuple(
        AdvisoryJournalDispositionRecord(
            datetime.fromisoformat(item["recorded_at"]),
            AdvisoryJournalDisposition(item["disposition"]),
            item["reason"],
        )
        for item in connection.execute(
            "SELECT * FROM advisory_journal_dispositions WHERE entry_id = ? ORDER BY recorded_at, record_id",
            (row["entry_id"],),
        ).fetchall()
    )
    return AdvisoryJournalEntry(
        row["entry_id"],
        row["advisory_id"],
        row["profile"],
        row["configuration_version"],
        datetime.fromisoformat(row["opened_at"]),
        datetime.fromisoformat(row["updated_at"]),
        None if row["disposition"] is None else AdvisoryJournalDisposition(row["disposition"]),
        None if row["disposition_at"] is None else datetime.fromisoformat(row["disposition_at"]),
        row["reason"],
        evidence,
        history,
    )


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_artifacts (
            artifact_id TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            universe TEXT NOT NULL,
            signal_definition TEXT NOT NULL,
            fee_rate TEXT NOT NULL,
            slippage_rate TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            total_return TEXT NOT NULL,
            benchmark_return TEXT NOT NULL,
            trade_count INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_journal (
            entry_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            summary TEXT NOT NULL,
            rationale TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_entries (
            entry_id TEXT PRIMARY KEY,
            advisory_id TEXT NOT NULL,
            profile TEXT NOT NULL,
            configuration_version TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            disposition TEXT CHECK(disposition IN (
                'accepted', 'rejected', 'partially_executed', 'deferred', 'expired'
            )),
            disposition_at TEXT,
            reason TEXT,
            CHECK(
                (disposition IS NULL AND disposition_at IS NULL AND reason IS NULL)
                OR (disposition IS NOT NULL AND disposition_at IS NOT NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_dispositions (
            record_id TEXT PRIMARY KEY,
            entry_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            disposition TEXT NOT NULL CHECK(disposition IN (
                'accepted', 'rejected', 'partially_executed', 'deferred', 'expired'
            )),
            reason TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_evidence (
            entry_id TEXT NOT NULL,
            event_fingerprint TEXT NOT NULL,
            linked_at TEXT NOT NULL,
            PRIMARY KEY(entry_id, event_fingerprint)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS advisory_journal_settings_audit (
            profile TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            open_on_advisory INTEGER NOT NULL,
            retention_days INTEGER,
            display_reasons INTEGER NOT NULL,
            configuration_version INTEGER NOT NULL,
            PRIMARY KEY(profile, changed_at, configuration_version)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_settings_audit (
            profile TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            configuration_version INTEGER NOT NULL,
            settings_json TEXT NOT NULL,
            PRIMARY KEY(profile, changed_at, configuration_version)
        )
        """
    )
