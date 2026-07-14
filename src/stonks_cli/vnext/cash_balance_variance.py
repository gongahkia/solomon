from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from stonks_cli.vnext.reconciliation import ImportedPortfolioReconciliation


@dataclass(frozen=True)
class CashBalanceVarianceAlert:
    imported_snapshot_id: UUID
    reference_snapshot_id: UUID
    cash_delta: float
    threshold: float
    triggered: bool

    def __post_init__(self) -> None:
        if not isinstance(self.imported_snapshot_id, UUID) or not isinstance(self.reference_snapshot_id, UUID):
            raise TypeError("cash-balance variance snapshot IDs must be UUIDs")
        if self.imported_snapshot_id == self.reference_snapshot_id:
            raise ValueError("cash-balance variance snapshots must differ")
        if not all(isinstance(value, float) and math.isfinite(value) for value in (self.cash_delta, self.threshold)) or self.threshold < 0:
            raise ValueError("cash-balance variance values are invalid")
        if not isinstance(self.triggered, bool) or self.triggered is not (abs(self.cash_delta) > self.threshold):
            raise ValueError("cash-balance variance trigger is inconsistent")


def alert_on_cash_balance_variance(
    reconciliation: ImportedPortfolioReconciliation,
    *,
    threshold: float,
) -> CashBalanceVarianceAlert:
    if not isinstance(reconciliation, ImportedPortfolioReconciliation):
        raise TypeError("cash-balance variance requires imported-portfolio reconciliation")
    if not isinstance(threshold, float) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("cash-balance variance threshold is invalid")
    return CashBalanceVarianceAlert(
        reconciliation.imported_snapshot_id,
        reconciliation.reference_snapshot_id,
        reconciliation.cash_delta,
        threshold,
        abs(reconciliation.cash_delta) > threshold,
    )
