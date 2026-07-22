from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class Currency(StrEnum):
    CNY = "CNY"
    HKD = "HKD"
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


class EventLifecycle(StrEnum):
    POSTED = "posted"
    CORRECTION = "correction"
    REVERSAL = "reversal"


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
        symbol = self.symbol.strip().upper()
        market = self.market.strip().upper()
        if not symbol or not market:
            raise ValueError("instrument symbol and market are required")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "market", market)

    @property
    def key(self) -> str:
        return f"{self.market.upper()}:{self.symbol.upper()}"


@dataclass(frozen=True)
class Account:
    provider_id: str
    account_id: str
    name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not isinstance(self.account_id, str):
            raise ValueError("account provider and identifier are required")
        provider_id = self.provider_id.strip().lower()
        account_id = self.account_id.strip()
        if not provider_id or not account_id:
            raise ValueError("account provider and identifier are required")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "account_id", account_id)

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.account_id}"


@dataclass(frozen=True)
class SourceProvenance:
    provider_id: str
    source_hash: str
    record_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not isinstance(self.record_id, str):
            raise ValueError("source provider and record identifier are required")
        provider_id = self.provider_id.strip().lower()
        record_id = self.record_id.strip()
        if not provider_id or not record_id or not isinstance(self.source_hash, str):
            raise ValueError("source provider and record identifier are required")
        source_hash = self.source_hash.lower()
        if not _SHA256.fullmatch(source_hash):
            raise ValueError("source hash must be a SHA-256 digest")
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "source_hash", source_hash)
        object.__setattr__(self, "record_id", record_id)

    @property
    def key(self) -> str:
        return f"{self.provider_id}:{self.source_hash}:{self.record_id}"


@dataclass(frozen=True)
class BrokerPositionSnapshot:
    source: SourceProvenance
    account: Account
    instrument: Instrument
    quantity: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceProvenance) or not isinstance(self.account, Account):
            raise ValueError("source and account are required")
        if not isinstance(self.instrument, Instrument):
            raise ValueError("instrument is required")
        quantity = decimal(self.quantity)
        if quantity < 0:
            raise ValueError("snapshot quantity must be non-negative")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "observed_at", utc(self.observed_at))


@dataclass(frozen=True)
class BrokerCashSnapshot:
    source: SourceProvenance
    account: Account
    currency: Currency
    amount: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceProvenance) or not isinstance(self.account, Account):
            raise ValueError("source and account are required")
        if not isinstance(self.currency, Currency):
            raise ValueError("cash snapshot currency is required")
        object.__setattr__(self, "amount", decimal(self.amount))
        object.__setattr__(self, "observed_at", utc(self.observed_at))


@dataclass(frozen=True)
class BrokerCashFlow:
    source: SourceProvenance
    account: Account
    clearing_date: date
    settlement_date: date
    currency: Currency
    flow_type: str
    direction: str
    amount: Decimal
    remark: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, SourceProvenance) or not isinstance(self.account, Account):
            raise ValueError("source and account are required")
        if not isinstance(self.clearing_date, date) or not isinstance(self.settlement_date, date):
            raise ValueError("cash flow dates are required")
        if not isinstance(self.currency, Currency):
            raise ValueError("cash flow currency is required")
        flow_type = self.flow_type.strip()
        direction = self.direction.strip()
        if not flow_type or not direction:
            raise ValueError("cash flow type and direction are required")
        object.__setattr__(self, "flow_type", flow_type)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "amount", decimal(self.amount))
        if self.remark is not None:
            remark = self.remark.strip()
            object.__setattr__(self, "remark", remark or None)


@dataclass(frozen=True)
class LedgerEvent:
    fingerprint: str
    source: SourceProvenance
    account: Account
    occurred_at: datetime
    kind: EventKind
    currency: Currency
    amount: Decimal
    quantity: Decimal = Decimal("0")
    instrument: Instrument | None = None
    fee: Decimal = Decimal("0")
    lifecycle: EventLifecycle = EventLifecycle.POSTED
    corrects_fingerprint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.fingerprint, str) or not (fingerprint := self.fingerprint.strip()):
            raise ValueError("fingerprint is required")
        if not isinstance(self.source, SourceProvenance) or not isinstance(self.account, Account):
            raise ValueError("source and account are required")
        if not isinstance(self.lifecycle, EventLifecycle):
            raise ValueError("lifecycle is required")
        object.__setattr__(self, "fingerprint", fingerprint)
        corrects_fingerprint = self.corrects_fingerprint
        if self.lifecycle is EventLifecycle.POSTED:
            if corrects_fingerprint is not None:
                raise ValueError("posted events cannot correct another event")
        else:
            if not isinstance(corrects_fingerprint, str) or not (
                corrects_fingerprint := corrects_fingerprint.strip()
            ):
                raise ValueError("corrections require a target fingerprint")
            if corrects_fingerprint == fingerprint:
                raise ValueError("events cannot correct themselves")
            object.__setattr__(self, "corrects_fingerprint", corrects_fingerprint)
        object.__setattr__(self, "occurred_at", utc(self.occurred_at))
        object.__setattr__(self, "amount", decimal(self.amount))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "fee", decimal(self.fee))
        if self.amount < 0 or self.fee < 0:
            raise ValueError("amount and fee must be non-negative")
        if self.kind in {EventKind.CASH_DEPOSIT, EventKind.CASH_WITHDRAWAL}:
            if self.amount <= 0:
                raise ValueError("cash transfers require a positive amount")
            if self.instrument is not None or self.quantity != 0 or self.fee != 0:
                raise ValueError("cash transfers cannot include instrument, quantity, or fee")
        if self.kind is EventKind.FEE:
            if self.amount <= 0:
                raise ValueError("fee events require a positive amount")
            if self.instrument is not None or self.quantity != 0 or self.fee != 0:
                raise ValueError("fee events cannot include instrument, quantity, or fee")
        if self.kind is EventKind.DIVIDEND:
            if self.amount <= 0 or self.instrument is None:
                raise ValueError("dividends require an instrument and positive amount")
            if self.fee != 0:
                raise ValueError("dividend events cannot include a fee")
        if self.kind in {EventKind.BUY, EventKind.SELL}:
            if self.instrument is None or self.quantity <= 0:
                raise ValueError("trades require an instrument and positive quantity")
            if self.amount <= 0:
                raise ValueError("trades require a positive amount")
        if self.kind is EventKind.SPLIT:
            if self.instrument is None or self.quantity <= 0:
                raise ValueError("splits require an instrument and positive ratio")
            if self.amount != 0 or self.fee != 0:
                raise ValueError("splits cannot include cash amount or fee")

    @property
    def source_id(self) -> str:
        return self.source.key

    @property
    def account_id(self) -> str:
        return self.account.key

    def to_data(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "source": {
                "provider_id": self.source.provider_id,
                "source_hash": self.source.source_hash,
                "record_id": self.source.record_id,
            },
            "account": {
                "provider_id": self.account.provider_id,
                "account_id": self.account.account_id,
                "name": self.account.name,
            },
            "occurred_at": self.occurred_at.isoformat(),
            "kind": self.kind.value,
            "lifecycle": self.lifecycle.value,
            "corrects_fingerprint": self.corrects_fingerprint,
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
