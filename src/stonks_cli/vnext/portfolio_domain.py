from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from stonks_cli.vnext.foundation import as_utc

_CURRENCY_PATTERN = re.compile(r"[A-Z]{3}\Z")


class PortfolioAssetClass(StrEnum):
    CASH = "cash"
    CRYPTO = "crypto"
    EQUITY = "equity"
    FUND = "fund"
    OTHER = "other"


@dataclass(frozen=True)
class PortfolioHolding:
    account_id: str
    holding_id: str
    symbol: str
    asset_class: PortfolioAssetClass
    quantity: float
    currency: str
    market_value: float

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value for value in (self.account_id, self.holding_id, self.symbol)):
            raise ValueError("portfolio holding identifiers are invalid")
        if not isinstance(self.asset_class, PortfolioAssetClass):
            raise ValueError("portfolio holding asset class is invalid")
        if not isinstance(self.quantity, float) or not math.isfinite(self.quantity) or self.quantity == 0:
            raise ValueError("portfolio holding quantity is invalid")
        if not isinstance(self.currency, str) or not _CURRENCY_PATTERN.fullmatch(self.currency):
            raise ValueError("portfolio holding currency is invalid")
        if not isinstance(self.market_value, float) or not math.isfinite(self.market_value) or self.market_value == 0:
            raise ValueError("portfolio holding market value is invalid")
        if math.copysign(1, self.quantity) != math.copysign(1, self.market_value):
            raise ValueError("portfolio holding quantity and market value signs differ")


@dataclass(frozen=True)
class PortfolioSnapshot:
    provider_id: str
    account_id: str
    captured_at: datetime
    holdings: tuple[PortfolioHolding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id or not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("portfolio snapshot identifiers are invalid")
        object.__setattr__(self, "captured_at", as_utc(self.captured_at))
        if not isinstance(self.holdings, tuple) or not all(isinstance(holding, PortfolioHolding) for holding in self.holdings):
            raise ValueError("portfolio snapshot holdings are invalid")
        if any(holding.account_id != self.account_id for holding in self.holdings):
            raise ValueError("portfolio snapshot holdings use a different account")
        holding_ids = tuple(holding.holding_id for holding in self.holdings)
        if len(set(holding_ids)) != len(holding_ids):
            raise ValueError("portfolio snapshot holding IDs must be unique")
        if self.holdings != tuple(sorted(self.holdings, key=lambda holding: (holding.symbol, holding.holding_id))):
            raise ValueError("portfolio snapshot holdings are not canonical")
