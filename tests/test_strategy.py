from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import encrypted_ledger

from stonks_cli.config import JournalSettings
from stonks_cli.ledger import append
from stonks_cli.strategy import (
    AdvisoryJournalDisposition,
    DailyBar,
    StrategyRunCard,
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
    run_csv_backtest,
    simulate_eod_long_only,
    store_artifact,
)
from stonks_cli.types import Account, Currency, EventKind, Instrument, LedgerEvent, SourceProvenance


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
    assert list_advisory_journal_entries(
        ledger, retention_days=settings.retention_days, now=datetime(2026, 1, 10, tzinfo=UTC)
    ) == ()
