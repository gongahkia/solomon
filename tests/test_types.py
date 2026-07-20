from __future__ import annotations

from decimal import Decimal

import pytest

from stonks_cli.types import Currency, decimal


def test_money_uses_exact_decimal_values_and_supported_currencies() -> None:
    assert decimal("12.340") == Decimal("12.340")
    assert decimal(7) == Decimal("7")
    assert {currency.value for currency in Currency} == {"SGD", "USD"}


@pytest.mark.parametrize("value", ("NaN", "Infinity", "not-money"))
def test_money_rejects_non_finite_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        decimal(value)
