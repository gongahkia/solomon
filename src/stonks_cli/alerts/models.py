from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Alert:
    """Alert definition."""

    ticker: str
    condition_type: str
    threshold: float
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    triggered_at: datetime | None = None
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "condition_type": self.condition_type,
            "threshold": self.threshold,
            "created_at": self.created_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Alert:
        return cls(
            id=data["id"],
            ticker=data["ticker"],
            condition_type=data["condition_type"],
            threshold=data["threshold"],
            created_at=datetime.fromisoformat(data["created_at"]),
            triggered_at=datetime.fromisoformat(data["triggered_at"]) if data.get("triggered_at") else None,
            enabled=data.get("enabled", True),
        )
