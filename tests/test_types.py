from __future__ import annotations

from decimal import Decimal

import pytest

from stonks_cli.types import Account, Currency, Instrument, SourceProvenance, decimal


def test_money_uses_exact_decimal_values_and_supported_currencies() -> None:
    assert decimal("12.340") == Decimal("12.340")
    assert decimal(7) == Decimal("7")
    assert {currency.value for currency in Currency} == {"SGD", "USD"}


@pytest.mark.parametrize("value", ("NaN", "Infinity", "not-money"))
def test_money_rejects_non_finite_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        decimal(value)


def test_instrument_identity_is_trimmed_and_canonicalized() -> None:
    instrument = Instrument(" spy ", " us ", Currency.USD, "S&P 500 ETF")
    assert instrument.symbol == "SPY"
    assert instrument.market == "US"
    assert instrument.key == "US:SPY"


@pytest.mark.parametrize("symbol,market", (("", "US"), ("SPY", " ")))
def test_instrument_identity_requires_symbol_and_market(symbol: str, market: str) -> None:
    with pytest.raises(ValueError, match="required"):
        Instrument(symbol, market, Currency.USD)


def test_account_identity_is_provider_qualified_and_canonicalized() -> None:
    account = Account(" Moomoo ", " 123 ", "Personal")
    assert account.provider_id == "moomoo"
    assert account.account_id == "123"
    assert account.key == "moomoo:123"


@pytest.mark.parametrize("provider_id,account_id", (("", "123"), ("csv", "  ")))
def test_account_identity_requires_provider_and_identifier(
    provider_id: str, account_id: str
) -> None:
    with pytest.raises(ValueError, match="required"):
        Account(provider_id, account_id)


def test_source_provenance_is_immutable_and_canonicalized() -> None:
    provenance = SourceProvenance(" CSV ", "A" * 64, " line-7 ")
    assert provenance.provider_id == "csv"
    assert provenance.source_hash == "a" * 64
    assert provenance.record_id == "line-7"
    assert provenance.key == f"csv:{'a' * 64}:line-7"


@pytest.mark.parametrize("source_hash", ("short", "g" * 64))
def test_source_provenance_requires_sha256_digest(source_hash: str) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        SourceProvenance("csv", source_hash, "line-1")
