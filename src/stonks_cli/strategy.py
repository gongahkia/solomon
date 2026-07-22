from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from stonks_cli.errors import ProviderError
from stonks_cli.storage import EncryptedLedger


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
            for value in (self.strategy_name, self.universe, self.signal_definition, self.source_hash)
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
        rows = connection.execute("SELECT * FROM strategy_artifacts ORDER BY created_at, artifact_id").fetchall()
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
        rows = connection.execute("SELECT * FROM strategy_journal ORDER BY created_at, entry_id").fetchall()
    return tuple(
        StrategyJournalEntry(
            row["entry_id"],
            datetime.fromisoformat(row["created_at"]),
            row["summary"],
            row["rationale"],
        )
        for row in rows
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
