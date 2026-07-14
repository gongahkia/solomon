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
