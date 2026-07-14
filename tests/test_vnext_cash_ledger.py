from datetime import UTC, date, datetime

import pytest

from stonks_cli.vnext.cash_ledger import CashBalance, CashLedger, CashLedgerEntry


def test_cash_ledger_aggregates_canonical_signed_currency_balances():
    sgd = CashLedgerEntry("100", "sgd", date(2026, 7, 13), "SGD", -5.0, "fee")
    usd = CashLedgerEntry("100", "usd", date(2026, 7, 14), "USD", 10.0, "deposit")

    ledger = CashLedger("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (sgd, usd))

    assert ledger.balances == (CashBalance("SGD", -5.0), CashBalance("USD", 10.0))


def test_cash_ledger_fails_closed_for_invalid_or_noncanonical_entries():
    with pytest.raises(ValueError, match="amount"):
        CashLedgerEntry("100", "zero", date(2026, 7, 14), "USD", 0.0, "zero")

    apple = CashLedgerEntry("100", "apple", date(2026, 7, 13), "USD", 10.0, "deposit")
    banana = CashLedgerEntry("100", "banana", date(2026, 7, 14), "USD", -2.0, "fee")
    with pytest.raises(ValueError, match="canonical"):
        CashLedger("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (banana, apple))
    with pytest.raises(ValueError, match="unique"):
        CashLedger("moomoo", "100", datetime(2026, 7, 14, 12, tzinfo=UTC), (apple, apple))
