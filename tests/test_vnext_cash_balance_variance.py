from __future__ import annotations

from uuid import UUID

import pytest

from stonks_cli.vnext.cash_balance_variance import CashBalanceVarianceAlert, alert_on_cash_balance_variance
from stonks_cli.vnext.reconciliation import ImportedPortfolioReconciliation


def test_cash_balance_variance_alert_triggers_only_above_the_explicit_threshold():
    reconciliation = _reconciliation(2.0)

    assert alert_on_cash_balance_variance(reconciliation, threshold=2.0).triggered is False
    alert = alert_on_cash_balance_variance(reconciliation, threshold=1.0)
    assert alert.triggered is True
    assert alert.cash_delta == 2.0


@pytest.mark.parametrize("cash_delta,threshold", [(None, 1.0), (2.0, -1.0), (2.0, float("nan"))])
def test_cash_balance_variance_alert_fails_closed_for_missing_or_malformed_external_data(cash_delta, threshold):
    reconciliation = None if cash_delta is None else _reconciliation(cash_delta)
    with pytest.raises((TypeError, ValueError), match="cash-balance variance"):
        alert_on_cash_balance_variance(reconciliation, threshold=threshold)  # type: ignore[arg-type]


@pytest.mark.parametrize("triggered", [False, "true"])
def test_cash_balance_variance_alert_rejects_inconsistent_or_malformed_results(triggered):
    with pytest.raises((TypeError, ValueError), match="cash-balance variance"):
        CashBalanceVarianceAlert(
            UUID("00000000-0000-4000-8000-000000000001"),
            UUID("00000000-0000-4000-8000-000000000002"),
            2.0,
            1.0,
            triggered,  # type: ignore[arg-type]
        )


def _reconciliation(cash_delta: float) -> ImportedPortfolioReconciliation:
    return ImportedPortfolioReconciliation(
        UUID("00000000-0000-4000-8000-000000000001"),
        UUID("00000000-0000-4000-8000-000000000002"),
        cash_delta,
        (),
    )
