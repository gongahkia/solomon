from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stonks_cli.vnext.foundation import as_utc

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")
_SOURCE_ID_PATTERN = re.compile(r"[a-z][a-z0-9._-]*\Z")
_SYMBOL_PATTERN = re.compile(r"[A-Z][A-Z0-9._-]*\Z")


@dataclass(frozen=True)
class ReconciliationPosition:
    symbol: str
    quantity: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not _SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("reconciliation position symbol is invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity <= 0:
            raise ValueError("reconciliation position quantity is invalid")

    def to_data(self) -> dict[str, object]:
        return {"symbol": self.symbol, "quantity": self.quantity}

    @classmethod
    def from_data(cls, data: object) -> ReconciliationPosition:
        if not isinstance(data, dict) or set(data) != {"symbol", "quantity"} or not isinstance(data["symbol"], str) or not isinstance(data["quantity"], float):
            raise ValueError("reconciliation position fields are invalid")
        try:
            return cls(data["symbol"], data["quantity"])
        except (TypeError, ValueError) as error:
            raise ValueError("reconciliation position is malformed") from error


@dataclass(frozen=True)
class ReconciliationSnapshot:
    snapshot_id: UUID
    source_id: str
    captured_at: datetime
    currency: str
    cash_balance: float
    positions: tuple[ReconciliationPosition, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, UUID):
            raise TypeError("reconciliation snapshot ID must be a UUID")
        if not isinstance(self.source_id, str) or not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("reconciliation snapshot source ID is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("reconciliation snapshot currency is invalid")
        if not isinstance(self.cash_balance, float) or not math.isfinite(self.cash_balance) or self.cash_balance < 0:
            raise ValueError("reconciliation snapshot cash balance is invalid")
        if not isinstance(self.positions, tuple) or not all(isinstance(position, ReconciliationPosition) for position in self.positions):
            raise ValueError("reconciliation snapshot positions are invalid")
        symbols = tuple(position.symbol for position in self.positions)
        if symbols != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
            raise ValueError("reconciliation snapshot positions are not canonical")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))

    def to_data(self) -> dict[str, object]:
        return {
            "snapshot_id": str(self.snapshot_id),
            "source_id": self.source_id,
            "captured_at": self.captured_at.isoformat().replace("+00:00", "Z"),
            "currency": self.currency,
            "cash_balance": self.cash_balance,
            "positions": [position.to_data() for position in self.positions],
        }

    @classmethod
    def from_data(cls, data: object) -> ReconciliationSnapshot:
        fields = {"snapshot_id", "source_id", "captured_at", "currency", "cash_balance", "positions"}
        if not isinstance(data, dict) or set(data) != fields:
            raise ValueError("reconciliation snapshot fields are invalid")
        if not all(isinstance(data[field], str) for field in ("snapshot_id", "source_id", "captured_at", "currency")) or not isinstance(data["cash_balance"], float) or not isinstance(data["positions"], list):
            raise ValueError("reconciliation snapshot fields are invalid")
        try:
            return cls(
                UUID(data["snapshot_id"]),
                data["source_id"],
                datetime.fromisoformat(data["captured_at"]),
                data["currency"],
                data["cash_balance"],
                tuple(ReconciliationPosition.from_data(position) for position in data["positions"]),
            )
        except (TypeError, ValueError) as error:
            raise ValueError("reconciliation snapshot is malformed") from error


@dataclass(frozen=True)
class ReconciliationDifference:
    symbol: str
    imported_quantity: float
    reference_quantity: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not _SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("reconciliation difference symbol is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) and value >= 0 for value in (self.imported_quantity, self.reference_quantity)):
            raise ValueError("reconciliation difference quantities are invalid")
        if math.isclose(self.imported_quantity, self.reference_quantity, rel_tol=0.0, abs_tol=0.0):
            raise ValueError("reconciliation difference must differ")

    @property
    def quantity_delta(self) -> float:
        return math.fsum((self.imported_quantity, -self.reference_quantity))


@dataclass(frozen=True)
class ImportedPortfolioReconciliation:
    imported_snapshot_id: UUID
    reference_snapshot_id: UUID
    cash_delta: float
    position_differences: tuple[ReconciliationDifference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.imported_snapshot_id, UUID) or not isinstance(self.reference_snapshot_id, UUID):
            raise TypeError("imported-portfolio reconciliation snapshot IDs must be UUIDs")
        if self.imported_snapshot_id == self.reference_snapshot_id:
            raise ValueError("imported-portfolio reconciliation snapshots must differ")
        if not isinstance(self.cash_delta, float) or not math.isfinite(self.cash_delta):
            raise ValueError("imported-portfolio reconciliation cash delta is invalid")
        if not isinstance(self.position_differences, tuple) or not all(isinstance(item, ReconciliationDifference) for item in self.position_differences):
            raise ValueError("imported-portfolio reconciliation differences are invalid")
        symbols = tuple(item.symbol for item in self.position_differences)
        if symbols != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
            raise ValueError("imported-portfolio reconciliation differences are not canonical")

    @property
    def matches(self) -> bool:
        return self.cash_delta == 0.0 and not self.position_differences


def reconcile_imported_portfolio_state(
    imported: ReconciliationSnapshot,
    reference: ReconciliationSnapshot,
    *,
    tolerance: float = 1e-12,
) -> ImportedPortfolioReconciliation:
    if not isinstance(imported, ReconciliationSnapshot) or not isinstance(reference, ReconciliationSnapshot):
        raise TypeError("imported-portfolio reconciliation requires snapshots")
    if imported.source_id != "imported.portfolio" or imported.source_id == reference.source_id:
        raise ValueError("imported-portfolio reconciliation sources are invalid")
    if imported.currency != reference.currency or imported.captured_at != reference.captured_at:
        raise ValueError("imported-portfolio reconciliation snapshots are incompatible")
    if not isinstance(tolerance, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("imported-portfolio reconciliation tolerance is invalid")
    imported_positions = {position.symbol: position.quantity for position in imported.positions}
    reference_positions = {position.symbol: position.quantity for position in reference.positions}
    differences = tuple(
        ReconciliationDifference(symbol, imported_positions.get(symbol, 0.0), reference_positions.get(symbol, 0.0))
        for symbol in sorted(set(imported_positions) | set(reference_positions))
        if not math.isclose(imported_positions.get(symbol, 0.0), reference_positions.get(symbol, 0.0), rel_tol=0.0, abs_tol=tolerance)
    )
    cash_delta = math.fsum((imported.cash_balance, -reference.cash_balance))
    if math.isclose(cash_delta, 0.0, rel_tol=0.0, abs_tol=tolerance):
        cash_delta = 0.0
    return ImportedPortfolioReconciliation(imported.snapshot_id, reference.snapshot_id, cash_delta, differences)


@dataclass(frozen=True)
class BrokerSnapshotDifference:
    symbol: str
    earlier_quantity: float
    later_quantity: float

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not _SYMBOL_PATTERN.fullmatch(self.symbol):
            raise ValueError("broker-snapshot difference symbol is invalid")
        if not all(isinstance(value, float) and math.isfinite(value) and value >= 0 for value in (self.earlier_quantity, self.later_quantity)):
            raise ValueError("broker-snapshot difference quantities are invalid")
        if math.isclose(self.earlier_quantity, self.later_quantity, rel_tol=0.0, abs_tol=0.0):
            raise ValueError("broker-snapshot difference must differ")

    @property
    def quantity_delta(self) -> float:
        return math.fsum((self.later_quantity, -self.earlier_quantity))


@dataclass(frozen=True)
class BrokerSnapshotReconciliation:
    earlier_snapshot_id: UUID
    later_snapshot_id: UUID
    cash_delta: float
    position_differences: tuple[BrokerSnapshotDifference, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.earlier_snapshot_id, UUID) or not isinstance(self.later_snapshot_id, UUID):
            raise TypeError("broker-snapshot reconciliation snapshot IDs must be UUIDs")
        if self.earlier_snapshot_id == self.later_snapshot_id:
            raise ValueError("broker-snapshot reconciliation snapshots must differ")
        if not isinstance(self.cash_delta, float) or not math.isfinite(self.cash_delta):
            raise ValueError("broker-snapshot reconciliation cash delta is invalid")
        if not isinstance(self.position_differences, tuple) or not all(isinstance(item, BrokerSnapshotDifference) for item in self.position_differences):
            raise ValueError("broker-snapshot reconciliation differences are invalid")
        symbols = tuple(item.symbol for item in self.position_differences)
        if symbols != tuple(sorted(symbols)) or len(set(symbols)) != len(symbols):
            raise ValueError("broker-snapshot reconciliation differences are not canonical")

    @property
    def matches(self) -> bool:
        return self.cash_delta == 0.0 and not self.position_differences


def reconcile_broker_snapshots(
    earlier: ReconciliationSnapshot,
    later: ReconciliationSnapshot,
    *,
    tolerance: float = 1e-12,
) -> BrokerSnapshotReconciliation:
    if not isinstance(earlier, ReconciliationSnapshot) or not isinstance(later, ReconciliationSnapshot):
        raise TypeError("broker-snapshot reconciliation requires snapshots")
    if earlier.source_id != "broker.snapshot" or later.source_id != "broker.snapshot":
        raise ValueError("broker-snapshot reconciliation sources are invalid")
    if earlier.currency != later.currency or earlier.captured_at >= later.captured_at:
        raise ValueError("broker-snapshot reconciliation snapshots are incompatible")
    if not isinstance(tolerance, float) or not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("broker-snapshot reconciliation tolerance is invalid")
    earlier_positions = {position.symbol: position.quantity for position in earlier.positions}
    later_positions = {position.symbol: position.quantity for position in later.positions}
    differences = tuple(
        BrokerSnapshotDifference(symbol, earlier_positions.get(symbol, 0.0), later_positions.get(symbol, 0.0))
        for symbol in sorted(set(earlier_positions) | set(later_positions))
        if not math.isclose(earlier_positions.get(symbol, 0.0), later_positions.get(symbol, 0.0), rel_tol=0.0, abs_tol=tolerance)
    )
    cash_delta = math.fsum((later.cash_balance, -earlier.cash_balance))
    if math.isclose(cash_delta, 0.0, rel_tol=0.0, abs_tol=tolerance):
        cash_delta = 0.0
    return BrokerSnapshotReconciliation(earlier.snapshot_id, later.snapshot_id, cash_delta, differences)
