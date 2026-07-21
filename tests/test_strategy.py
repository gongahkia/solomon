from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import encrypted_ledger

from stonks_cli.strategy import DailyBar, run_csv_backtest, simulate_eod_long_only


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
