from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Position:
    """Represents a single stock position in a portfolio."""

    ticker: str
    shares: float
    cost_basis_per_share: float
    purchase_date: date
    notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "shares": self.shares,
            "cost_basis_per_share": self.cost_basis_per_share,
            "purchase_date": self.purchase_date.isoformat(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Position:
        return cls(
            ticker=data["ticker"],
            shares=data["shares"],
            cost_basis_per_share=data["cost_basis_per_share"],
            purchase_date=date.fromisoformat(data["purchase_date"]),
            notes=data.get("notes"),
        )


@dataclass
class Portfolio:
    """Represents a user's portfolio containing positions and cash."""

    positions: list[Position] = field(default_factory=list)
    cash_balance: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "positions": [p.to_dict() for p in self.positions],
            "cash_balance": self.cash_balance,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Portfolio:
        return cls(
            positions=[Position.from_dict(p) for p in data.get("positions", [])],
            cash_balance=data.get("cash_balance", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
        )
