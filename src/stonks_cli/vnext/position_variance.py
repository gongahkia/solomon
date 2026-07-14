from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from stonks_cli.vnext.reconciliation import ImportedPortfolioReconciliation, ReconciliationDifference


@dataclass(frozen=True)
class PositionVarianceAlert:
    imported_snapshot_id: UUID
    reference_snapshot_id: UUID
    difference: ReconciliationDifference
    threshold: float
    triggered: bool

    def __post_init__(self) -> None:
        if not isinstance(self.imported_snapshot_id, UUID) or not isinstance(self.reference_snapshot_id, UUID):
            raise TypeError("position-variance snapshot IDs must be UUIDs")
        if self.imported_snapshot_id == self.reference_snapshot_id:
            raise ValueError("position-variance snapshots must differ")
        if not isinstance(self.difference, ReconciliationDifference):
            raise TypeError("position-variance difference is invalid")
        if not isinstance(self.threshold, float) or not math.isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("position-variance threshold is invalid")
        if not isinstance(self.triggered, bool) or self.triggered is not (abs(self.difference.quantity_delta) > self.threshold):
            raise ValueError("position-variance trigger is inconsistent")


def alert_on_position_variance(
    reconciliation: ImportedPortfolioReconciliation,
    *,
    threshold: float,
) -> tuple[PositionVarianceAlert, ...]:
    if not isinstance(reconciliation, ImportedPortfolioReconciliation):
        raise TypeError("position-variance requires imported-portfolio reconciliation")
    if not isinstance(threshold, float) or not math.isfinite(threshold) or threshold < 0:
        raise ValueError("position-variance threshold is invalid")
    return tuple(
        PositionVarianceAlert(
            reconciliation.imported_snapshot_id,
            reconciliation.reference_snapshot_id,
            difference,
            threshold,
            abs(difference.quantity_delta) > threshold,
        )
        for difference in reconciliation.position_differences
    )
