from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from conftest import encrypted_ledger

from stonks_cli.strategy import (
    DailyBar,
    StrategyRunCard,
    append_journal_entry,
    buy_and_hold_return,
    list_artifacts,
    list_journal_entries,
    run_csv_backtest,
    simulate_eod_long_only,
    store_artifact,
)


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
