from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from stonks_cli.errors import ProviderError
from stonks_cli.storage import EncryptedLedger


@dataclass(frozen=True)
class DailyBar:
    close: Decimal
    signal: bool

    def __post_init__(self) -> None:
        if self.close <= 0:
            raise ValueError("daily close must be positive")


@dataclass(frozen=True)
class BacktestResult:
    total_return: Decimal
    periods: int
    trade_count: int
    strategy_values: tuple[Decimal, ...]


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
            value *= bars[index].close / bars[index - 1].close
        values.append(value)
    return BacktestResult(value - Decimal("1"), len(bars) - 1, trades, tuple(values))


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
        bars.append(DailyBar(Decimal(row["close"] or ""), signal in {"1", "true"}))
    return simulate_eod_long_only(bars, fee_rate=fee_rate, slippage_rate=slippage_rate), source_hash
