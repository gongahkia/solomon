from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import encrypted_ledger

from stonks_cli.config import (
    InsufficientDividendHistoryPolicy,
    JournalSettings,
    RelativeStrengthActionMode,
    StrategyAlgorithm,
    StrategySettings,
)
from stonks_cli.ledger import append
from stonks_cli.market_data import DailyPrice
from stonks_cli.strategy import (
    AdvisoryJournalDisposition,
    DailyBar,
    DividendObservation,
    SignalAction,
    SignalConfidence,
    SignalStatus,
    StrategyRunCard,
    StrategySignalInput,
    append_journal_entry,
    buy_and_hold_return,
    journal_settings_audit,
    link_advisory_journal_evidence,
    list_advisory_journal_entries,
    list_artifacts,
    list_journal_entries,
    open_advisory_journal,
    record_advisory_journal_disposition,
    record_journal_settings_audit,
    record_strategy_settings_audit,
    run_csv_backtest,
    run_daily_bar_signals,
    simulate_eod_long_only,
    store_artifact,
    strategy_settings_audit,
)
from stonks_cli.types import (
    Account,
    AssetClass,
    Currency,
    EventKind,
    Instrument,
    InstrumentMaster,
    LedgerEvent,
    ListingStatus,
    SourceProvenance,
)


def _signal_input(
    symbol: str,
    closes: tuple[str, ...],
    *,
    dividends: tuple[DividendObservation, ...] = (),
) -> StrategySignalInput:
    instrument = InstrumentMaster(
        f"US:{symbol}",
        "NASDAQ",
        "US",
        Currency.USD,
        AssetClass.EQUITY,
        f"US.{symbol}",
        ListingStatus.LISTED,
        "fixture-1",
        "a" * 64,
    )
    start = date(2026, 1, 1)
    prices = tuple(
        DailyPrice(
            Instrument(symbol, "US", Currency.USD),
            start + timedelta(days=index),
            Decimal(close),
            "b" * 64,
        )
        for index, close in enumerate(closes)
    )
    return StrategySignalInput(instrument, prices, dividends)


def test_strategy_uses_prior_close_signal_only() -> None:
    result = simulate_eod_long_only(
        [
            DailyBar(Decimal("100"), True),
            DailyBar(Decimal("110"), False),
            DailyBar(Decimal("100"), False),
        ],
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    assert result.trade_count == 2
    assert result.total_return == Decimal("0.10")


def test_strategy_split_ratio_prevents_a_false_split_loss() -> None:
    result = simulate_eod_long_only(
        (
            DailyBar(Decimal("100"), True),
            DailyBar(Decimal("50"), True, Decimal("2")),
        ),
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )

    assert result.total_return == Decimal("0")
    assert buy_and_hold_return(
        (DailyBar(Decimal("100"), True), DailyBar(Decimal("50"), True, Decimal("2")))
    ) == Decimal("0")


def test_price_trend_signal_requires_completed_closes_and_preserves_exit_rule() -> None:
    settings = StrategySettings(
        enabled_algorithms=(StrategyAlgorithm.PRICE_TREND,),
        primary_algorithm=StrategyAlgorithm.PRICE_TREND,
        trend_exit_sma_days=3,
        trend_exit_consecutive_closes=2,
        version=4,
    )
    input_value = _signal_input("AAA", ("100", "100", "100", "90", "89"))

    artifact = run_daily_bar_signals((input_value,), settings)

    signal = artifact.summaries[0].primary_signal
    assert artifact.configuration_version == 4
    assert signal.action is SignalAction.SELL
    assert signal.confidence is SignalConfidence.HIGH
    assert signal.status is SignalStatus.AVAILABLE
    assert "profit alone is not an exit condition" in signal.rationale
    assert run_daily_bar_signals((input_value,), settings) == artifact


def test_relative_strength_ranking_can_become_an_explicit_conflicting_policy() -> None:
    inputs = (
        _signal_input("AAA", ("100", "100", "101")),
        _signal_input("BBB", ("100", "150", "200")),
    )
    settings = StrategySettings(
        trend_exit_sma_days=2,
        trend_exit_consecutive_closes=2,
        relative_strength_lookback_sessions=2,
    )

    ranking = run_daily_bar_signals(inputs, settings)
    ranking_summary = ranking.summaries[0]
    ranking_signal = next(
        item
        for item in ranking_summary.policy_signals
        if item.declaration.algorithm is StrategyAlgorithm.RELATIVE_STRENGTH
    )
    assert ranking_signal.action is SignalAction.HOLD
    assert not ranking_summary.conflict

    independent = run_daily_bar_signals(
        inputs,
        replace(
            settings,
            relative_strength_action_mode=RelativeStrengthActionMode.INDEPENDENT_BUY_SELL,
            version=2,
        ),
    )
    summary = independent.summaries[0]
    relative_strength = next(
        item
        for item in summary.policy_signals
        if item.declaration.algorithm is StrategyAlgorithm.RELATIVE_STRENGTH
    )

    assert summary.primary_signal.action is SignalAction.BUY
    assert relative_strength.action is SignalAction.SELL
    assert summary.conflict
    assert summary.displayed_confidence is SignalConfidence.CONFLICTED


def test_dividend_quality_abstains_or_downranks_without_treating_cash_as_available() -> None:
    input_value = _signal_input(
        "AAA",
        ("100", "101", "102"),
        dividends=(
            DividendObservation(date(2025, 1, 1), Decimal("1"), Currency.USD, "c" * 64),
            DividendObservation(date(2025, 4, 1), Decimal("1"), Currency.USD, "d" * 64),
        ),
    )
    settings = StrategySettings(
        enabled_algorithms=(StrategyAlgorithm.DIVIDEND_QUALITY,),
        primary_algorithm=StrategyAlgorithm.DIVIDEND_QUALITY,
        dividend_quality_minimum_observations=3,
    )

    abstained = run_daily_bar_signals((input_value,), settings).summaries[0].primary_signal
    lowered = (
        run_daily_bar_signals(
            (input_value,),
            replace(
                settings,
                insufficient_dividend_history_policy=InsufficientDividendHistoryPolicy.LOWER_RANK,
                version=2,
            ),
        )
        .summaries[0]
        .primary_signal
    )

    assert abstained.action is SignalAction.ABSTAIN
    assert abstained.status is SignalStatus.INSUFFICIENT_HISTORY
    assert lowered.action is SignalAction.HOLD
    assert lowered.status is SignalStatus.INSUFFICIENT_HISTORY_DOWNRANKED
    assert "dividend quality does not create available cash" in lowered.rationale


def test_csv_backtest_archives_source(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "strategy.csv"
    source.write_text("close,signal\n100,true\n110,false\n")
    result, source_hash = run_csv_backtest(
        encrypted_ledger(tmp_path, monkeypatch),
        source,
        fee_rate=Decimal("0"),
        slippage_rate=Decimal("0"),
    )
    assert result.total_return == Decimal("0.10")
    assert len(source_hash) == 64


def test_strategy_artifacts_and_manual_journal_are_encrypted(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    bars = (DailyBar(Decimal("100"), True), DailyBar(Decimal("110"), True))
    result = simulate_eod_long_only(bars, fee_rate=Decimal("0"), slippage_rate=Decimal("0"))
    card = StrategyRunCard(
        "baseline",
        "US:SPY",
        "prior-close signal",
        Decimal("0"),
        Decimal("0"),
        "a" * 64,
        datetime(2026, 1, 1, tzinfo=UTC),
    )
    artifact = store_artifact(ledger, card, result, buy_and_hold_return(bars))
    entry = append_journal_entry(ledger, "review", "signal is experimental")

    assert list_artifacts(ledger)[0].artifact_id == artifact.artifact_id
    assert list_journal_entries(ledger)[0].entry_id == entry.entry_id
    assert b"experimental" not in ledger.path.read_bytes()


def test_advisory_journal_records_disposition_and_imported_transaction_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    opened_at = datetime(2026, 1, 1, tzinfo=UTC)
    entry = open_advisory_journal(
        ledger, "advisory-1", "strategy:4", JournalSettings(), opened_at=opened_at
    )

    assert entry is not None
    assert entry.profile == "personal"
    assert entry.disposition is None
    assert (
        open_advisory_journal(
            ledger, "advisory-1", "strategy:4", JournalSettings(), opened_at=opened_at
        )
        == entry
    )
    assert append(
        ledger,
        LedgerEvent(
            "fill-1",
            SourceProvenance("csv", "a" * 64, "fill-1"),
            Account("csv", "main"),
            datetime(2026, 1, 2, tzinfo=UTC),
            EventKind.BUY,
            Currency.USD,
            Decimal("100"),
            Decimal("1"),
            Instrument("SPY", "US", Currency.USD),
        ),
    )
    with pytest.raises(ValueError, match="accepted"):
        link_advisory_journal_evidence(ledger, entry.entry_id, "fill-1")

    accepted = record_advisory_journal_disposition(
        ledger,
        entry.entry_id,
        AdvisoryJournalDisposition.ACCEPTED,
        reason="manual review",
        recorded_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert accepted.disposition is AdvisoryJournalDisposition.ACCEPTED
    assert accepted.disposition_history[-1].reason == "manual review"

    linked = link_advisory_journal_evidence(
        ledger, entry.entry_id, "fill-1", linked_at=datetime(2026, 1, 3, tzinfo=UTC)
    )

    assert linked.evidence_fingerprints == ("fill-1",)
    assert list_advisory_journal_entries(ledger) == (linked,)
    assert b"manual review" not in ledger.path.read_bytes()


def test_advisory_journal_honors_settings_retention_and_audit(tmp_path: Path, monkeypatch) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    settings = JournalSettings(False, 5, True, 2)
    assert open_advisory_journal(ledger, "advisory-1", "strategy:4", settings) is None
    entry = open_advisory_journal(
        ledger,
        "advisory-2",
        "strategy:4",
        JournalSettings(),
        opened_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert entry is not None
    record = record_journal_settings_audit(
        ledger, settings, changed_at=datetime(2026, 1, 10, tzinfo=UTC)
    )

    assert journal_settings_audit(ledger) == (record,)
    assert (
        list_advisory_journal_entries(
            ledger, retention_days=settings.retention_days, now=datetime(2026, 1, 10, tzinfo=UTC)
        )
        == ()
    )


def test_strategy_settings_audit_is_profile_scoped_and_encrypted(
    tmp_path: Path, monkeypatch
) -> None:
    ledger = encrypted_ledger(tmp_path, monkeypatch)
    settings = StrategySettings(risk_tolerance_selected=True, advisories_enabled=True, version=2)

    record = record_strategy_settings_audit(
        ledger, settings, changed_at=datetime(2026, 1, 10, tzinfo=UTC)
    )

    assert strategy_settings_audit(ledger) == (record,)
    assert b"manual_sell_advisory" not in ledger.path.read_bytes()
