from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from stonks_cli.vnext.foundation import as_utc

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


@dataclass(frozen=True)
class CashLedgerEntry:
    account_id: str
    entry_id: str
    settled_on: date
    currency: str
    amount: float
    description: str

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.entry_id, self.description)):
            raise ValueError("cash-ledger entry identifiers are invalid")
        if not isinstance(self.settled_on, date):
            raise TypeError("cash-ledger settlement date is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("cash-ledger currency is invalid")
        if not isinstance(self.amount, float) or not math.isfinite(self.amount) or self.amount == 0:
            raise ValueError("cash-ledger amount is invalid")


@dataclass(frozen=True)
class CashBalance:
    currency: str
    amount: float

    def __post_init__(self) -> None:
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("cash balance currency is invalid")
        if not isinstance(self.amount, float) or not math.isfinite(self.amount):
            raise ValueError("cash balance amount is invalid")


@dataclass(frozen=True)
class CashLedger:
    provider_id: str
    account_id: str
    captured_at: datetime
    entries: tuple[CashLedgerEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("cash ledger identifiers are invalid")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))
        if not isinstance(self.entries, tuple) or not all(isinstance(entry, CashLedgerEntry) for entry in self.entries):
            raise ValueError("cash-ledger entries are invalid")
        if any(entry.account_id != self.account_id for entry in self.entries):
            raise ValueError("cash-ledger entries use a different account")
        entry_ids = tuple(entry.entry_id for entry in self.entries)
        if len(set(entry_ids)) != len(entry_ids):
            raise ValueError("cash-ledger entry IDs must be unique")
        if self.entries != tuple(sorted(self.entries, key=lambda entry: (entry.settled_on, entry.entry_id))):
            raise ValueError("cash-ledger entries are not canonical")

    @property
    def balances(self) -> tuple[CashBalance, ...]:
        amounts: dict[str, list[float]] = {}
        for entry in self.entries:
            amounts.setdefault(entry.currency, []).append(entry.amount)
        try:
            return tuple(CashBalance(currency, math.fsum(amounts[currency])) for currency in sorted(amounts))
        except OverflowError as error:
            raise ValueError("cash-ledger balances overflow") from error
