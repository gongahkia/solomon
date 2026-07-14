from __future__ import annotations

from uuid import UUID

import pytest

from stonks_cli.vnext.position_variance import PositionVarianceAlert, alert_on_position_variance
from stonks_cli.vnext.reconciliation import ImportedPortfolioReconciliation, ReconciliationDifference


def test_position_variance_alerts_preserve_each_canonical_position_difference():
    alerts = alert_on_position_variance(_reconciliation(), threshold=1.0)

    assert tuple((alert.difference.symbol, alert.triggered) for alert in alerts) == (("US.AAPL", True), ("US.MSFT", False))


@pytest.mark.parametrize("missing,threshold", [(True, 1.0), (False, -1.0), (False, float("nan"))])
def test_position_variance_alerts_fail_closed_for_missing_or_malformed_external_data(missing, threshold):
    reconciliation = None if missing else _reconciliation()
    with pytest.raises((TypeError, ValueError), match="position-variance"):
        alert_on_position_variance(reconciliation, threshold=threshold)  # type: ignore[arg-type]


def test_position_variance_alert_rejects_an_inconsistent_trigger_result():
    with pytest.raises(ValueError, match="trigger is inconsistent"):
        PositionVarianceAlert(
            UUID("00000000-0000-4000-8000-000000000001"),
            UUID("00000000-0000-4000-8000-000000000002"),
            ReconciliationDifference("US.AAPL", 2.0, 1.0),
            0.5,
            False,
        )


def _reconciliation() -> ImportedPortfolioReconciliation:
    return ImportedPortfolioReconciliation(
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
        0.0,
        (ReconciliationDifference("US.AAPL", 2.0, 0.0), ReconciliationDifference("US.MSFT", 1.5, 1.0)),
    )
