from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class Currency(StrEnum):
    SGD = "SGD"
    USD = "USD"


class EventKind(StrEnum):
    CASH_DEPOSIT = "cash_deposit"
    CASH_WITHDRAWAL = "cash_withdrawal"
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    FEE = "fee"
    SPLIT = "split"


def decimal(value: Decimal | str | int | float) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"invalid decimal:{value}") from error
    if not result.is_finite():
        raise ValueError("decimal must be finite")
    return result


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class Instrument:
    symbol: str
    market: str
    currency: Currency
    name: str | None = None

    def __post_init__(self) -> None:
        if not self.symbol.strip() or not self.market.strip():
            raise ValueError("instrument symbol and market are required")

    @property
    def key(self) -> str:
        return f"{self.market.upper()}:{self.symbol.upper()}"


@dataclass(frozen=True)
class LedgerEvent:
    fingerprint: str
    source_id: str
    account_id: str
    occurred_at: datetime
    kind: EventKind
    currency: Currency
    amount: Decimal
    quantity: Decimal = Decimal("0")
    instrument: Instrument | None = None
    fee: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fingerprint or not self.source_id or not self.account_id:
            raise ValueError("fingerprint, source_id, and account_id are required")
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        object.__setattr__(self, "amount", decimal(self.amount))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "fee", decimal(self.fee))
        if self.amount < 0 or self.fee < 0:
            raise ValueError("amount and fee must be non-negative")
        if self.kind in {EventKind.BUY, EventKind.SELL} and (
            self.instrument is None or self.quantity <= 0
        ):
            raise ValueError("trades require an instrument and positive quantity")
        if self.kind is EventKind.SPLIT:
            if self.instrument is None or self.quantity <= 0:
                raise ValueError("splits require an instrument and positive ratio")

    def to_data(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "source_id": self.source_id,
            "account_id": self.account_id,
            "occurred_at": self.occurred_at.isoformat(),
            "kind": self.kind.value,
            "currency": self.currency.value,
            "amount": str(self.amount),
            "quantity": str(self.quantity),
            "instrument": None
            if self.instrument is None
            else {
                "symbol": self.instrument.symbol,
                "market": self.instrument.market,
                "currency": self.instrument.currency.value,
                "name": self.instrument.name,
            },
            "fee": str(self.fee),
            "metadata": self.metadata,
        }
