from __future__ import annotations

from decimal import Decimal

from stonks_cli.reconciliation import reconcile
from stonks_cli.types import Currency


def test_reconciliation_reports_only_real_differences() -> None:
    differences = reconcile(
        {("main", Currency.USD): Decimal("10")},
        {("main", Currency.USD): Decimal("11")},
        {("main", "US:SPY"): Decimal("2")},
        {("main", "US:SPY"): Decimal("2")},
    )
    assert differences[0].subject == "cash:main:USD"
    assert differences[0].delta == Decimal("1")
